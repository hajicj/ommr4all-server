from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from database import DatabasePage, DatabaseBook, DatabaseFile
from restapi.operationworker import operation_worker, TaskStatusCodes, TaskNotFoundException
import logging
import datetime
import json
import zipfile
import re
from database.file_formats.pcgts import PcGts, Coords
from database.file_formats.performance.pageprogress import PageProgress
from database.file_formats.performance.statistics import Statistics
from omr.stafflines.json_util import json_to_line
from restapi.operationworker import \
    TaskDataStaffLineDetection, TaskDataSymbolDetectionTrainer, TaskDataSymbolDetection, \
    TaskDataLayoutAnalysis

logger = logging.getLogger(__name__)


class OperationStatusView(APIView):
    # authentication_classes = (authentication.TokenAuthentication,)
    # permission_classes = (permissions.IsAdminUser,)

    def get(self, request, book, page, operation, format=None):
        page = DatabaseBook(book).page(page)

        # check if operation is linked to a task
        task_data = OperationView.op_to_task_data(operation, page)

        if task_data is not None:
            op_status = operation_worker.status(task_data)
            return Response({'status': op_status.to_json()})

        return Response(status=status.HTTP_204_NO_CONTENT)


class OperationView(APIView):
    @staticmethod
    def op_to_task_data(operation, page: DatabasePage):
        # check if operation is linked to a task
        if operation == 'staffs':
            return TaskDataStaffLineDetection(page)
        elif operation == 'symbols':
            return TaskDataSymbolDetection(page)
        elif operation == 'train_symbols':
            return TaskDataSymbolDetectionTrainer(page.book)
        elif operation == 'layout':
            return TaskDataLayoutAnalysis(page)
        else:
            return None

    def post(self, request, book, page, operation, format=None):
        page = DatabasePage(DatabaseBook(book), page)

        if operation == 'layout_extract_cc_by_line':
            obj = json.loads(request.body, encoding='utf-8')
            initial_line = Coords.from_json(obj['points'])
            from omr.layout.correction_tools.connected_component_selector import extract_components
            import pickle
            staff_lines = []
            for mr in PcGts.from_file(page.file('pcgts')).page.music_regions:
                for ml in mr.staffs:
                    staff_lines += ml.staff_lines

            with open(page.file('connected_components_deskewed', create_if_not_existing=True).local_path(), 'rb') as pkl:
                polys = extract_components(pickle.load(pkl), initial_line, staff_lines)

            return Response({'polys': [p.to_json() for p in polys]})
        elif operation == 'save_page_progress':
            obj = json.loads(request.body, encoding='utf-8')
            pp = PageProgress.from_json(obj)
            pp.to_json_file(page.file('page_progress').local_path())

            # add to backup archive
            with zipfile.ZipFile(page.file('page_progress_backup').local_path(), 'a', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('page_progress_{}.json'.format(datetime.datetime.now()), json.dumps(pp.to_json(), indent=2))

            logger.info('Successfully saved page progress file to {}'.format(page.file('page_progress').local_path()))

            return Response()
        elif operation == 'save_statistics':
            obj = json.loads(request.body, encoding='utf-8')
            total_stats = Statistics.from_json(obj)
            total_stats.to_json_file(page.file('statistics').local_path())

            # add to backup archive
            with zipfile.ZipFile(page.file('statistics_backup').local_path(), 'a', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('statistics_{}.json'.format(datetime.datetime.now()), json.dumps(total_stats.to_json(), indent=2))

            logger.info('Successfully saved statistics file to {}'.format(page.file('statistics').local_path()))

            return Response()
        elif operation == 'save':
            obj = json.loads(request.body, encoding='utf-8')
            pcgts = PcGts.from_json(obj, page)
            pcgts.to_file(page.file('pcgts').local_path())

            # add to backup archive
            with zipfile.ZipFile(page.file('pcgts_backup').local_path(), 'a', compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('pcgts_{}.json'.format(datetime.datetime.now()), json.dumps(pcgts.to_json(), indent=2))

            logger.info('Successfully saved pcgts file to {}'.format(page.file('pcgts').local_path()))

            return Response()
        elif operation == 'rename':
            obj = json.loads(request.body, encoding='utf-8')
            name = obj['name']
            name = re.sub('[^\w]', '_', name)

            if name != obj['name']:
                return Response(status=status.HTTP_406_NOT_ACCEPTABLE)

            page.rename(name)
            return Response()

        return Response(status=status.HTTP_400_BAD_REQUEST)

    def get(self, request, book, page, operation, format=None):
        page = DatabasePage(DatabaseBook(book), page)

        if operation == 'text_polygones':
            # TODO: currently unused
            obj = json.loads(request.body, encoding='utf-8')
            initial_line = json_to_line(obj['points'])
            from omr.segmentation.text.extract_text_from_intersection import extract_text
            import pickle
            f = page.file('connected_components_deskewed')
            f.create()
            with open(f.local_path(), 'rb') as pkl:
                text_line = extract_text(pickle.load(pkl), initial_line)

            return Response(text_line.to_json())

        task_data = OperationView.op_to_task_data(operation, page)
        if task_data:
            try:
                op_status = operation_worker.status(task_data)
                if op_status.code == TaskStatusCodes.FINISHED:
                    result = operation_worker.pop_result(task_data)
                    result['status'] = op_status.to_json()
                    return Response(result)
                elif op_status.code == TaskStatusCodes.ERROR:
                    error = operation_worker.pop_result(task_data)
                    raise error
                else:
                    return Response({'status': op_status.to_json()})
            except (FileNotFoundError, OSError) as e:
                logger.error(e)
                return Response({'error': 'no-model'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e:
                logging.error(e)
                return Response({'error': 'unknown'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            pass

        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def put(self, request, book, page, operation, format=None):
        page = DatabasePage(DatabaseBook(book), page)
        task_data = OperationView.op_to_task_data(operation, page)
        if task_data:
            try:
                if not operation_worker.put(task_data):
                    return Response(status=status.HTTP_303_SEE_OTHER)
                else:
                    return Response(status=status.HTTP_202_ACCEPTED)
            except Exception as e:
                logger.error(e)
                return Response(str(e), status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def delete(self, request, book, page, operation, format=None):
        page = DatabasePage(DatabaseBook(book), page)

        if operation == 'clean':
            for key, _ in DatabaseFile.file_definitions().items():
                if key != 'color_original':
                    DatabaseFile(page, key).delete()

            return Response()
        elif operation == 'delete':
            page.delete()
            return Response()

        task_data = OperationView.op_to_task_data(operation, page)
        if task_data:
            try:
                operation_worker.stop(task_data)
                return Response(status=status.HTTP_204_NO_CONTENT)
            except TaskNotFoundException as e:
                logger.warning(e)
                return Response(status=status.HTTP_204_NO_CONTENT)
            except Exception as e:
                logging.error(e)
                return Response({'error': 'unknown'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_204_NO_CONTENT)