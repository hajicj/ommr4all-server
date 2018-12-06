from main.operationworker import operation_worker, TaskStatusCodes, TaskNotFoundException
from main.operationworker import TaskDataSymbolDetection, TaskDataStaffLineDetection, TaskDataSymbolDetectionTrainer

from json import JSONDecodeError

from django.http import HttpResponse, JsonResponse, HttpResponseNotModified, HttpResponseBadRequest,\
    FileResponse

from omr.datatypes.performance.pageprogress import PageProgress
from .book import Book, Page, File, file_definitions, InvalidFileNameException
from omr.stafflines.json_util import json_to_line
from django.views.decorators.csrf import csrf_exempt
from omr.datatypes.performance.statistics import Statistics
import json
from omr.datatypes.pcgts import PcGts
import logging
import zipfile
import datetime
import os
import re

logger = logging.getLogger(__name__)


@csrf_exempt
def get_operation(request, book, page, operation):
    page = Page(Book(book), page)

    # check if operation is linked to a task
    if operation == 'staffs':
        task_data = TaskDataStaffLineDetection(page)
    elif operation == 'symbols':
        task_data = TaskDataSymbolDetection(page)
    elif operation == 'train_symbols':
        task_data = TaskDataSymbolDetectionTrainer(page.book)
    else:
        task_data = None

    if task_data is not None:
        # handle tasks
        if request.method == 'PUT':
            try:
                if not operation_worker.put(task_data):
                    return HttpResponse(status=303)
                else:
                    return HttpResponse(status=202)
            except Exception as e:
                logger.error(e)
                return HttpResponse(status=500, body=str(e))
        elif request.method == 'DELETE':
            try:
                operation_worker.stop(task_data)
                return HttpResponse(status=204)
            except TaskNotFoundException as e:
                logger.warning(e)
                return HttpResponse(status=204)
            except Exception as e:
                logging.error(e)
                return JsonResponse({'error': 'unknown'}, status=500)
        elif request.method == 'GET':
            try:
                status = operation_worker.status(task_data)
                if status.code == TaskStatusCodes.FINISHED:
                    result = operation_worker.pop_result(task_data)
                    result['status'] = status.to_json()
                    return JsonResponse(result)
                elif status.code == TaskStatusCodes.ERROR:
                    error = operation_worker.pop_result(task_data)
                    raise error
                else:
                    return JsonResponse({'status': status.to_json()})
            except TaskNotFoundException as e:
                logger.error(e)
                return HttpResponse(status=404)
            except (FileNotFoundError, OSError) as e:
                logger.error(e)
                return JsonResponse({'error': 'no-model'}, status=500)
            except Exception as e:
                logging.error(e)
                return JsonResponse({'error': 'unknown'}, status=500)
        elif request.method == 'DELETE':
            # TODO: delete task
            return HttpResponse()
        else:
            return HttpResponse(status=405)

    elif operation == 'text_polygones':
        obj = json.loads(request.body, encoding='utf-8')
        initial_line = json_to_line(obj['points'])
        from omr.segmentation.text.extract_text_from_intersection import extract_text
        import pickle
        f = page.file('connected_components_deskewed')
        f.create()
        with open(f.local_path(), 'rb') as pkl:
            text_line = extract_text(pickle.load(pkl), initial_line)

        return JsonResponse(text_line.to_json())

    elif operation == 'save_page_progress':
        obj = json.loads(request.body, encoding='utf-8')
        pp = PageProgress.from_json(obj)
        pp.to_json_file(page.file('page_progress').local_path())

        # add to backup archive
        with zipfile.ZipFile(page.file('page_progress_backup').local_path(), 'a', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('page_progress_{}.json'.format(datetime.datetime.now()), json.dumps(pp.to_json(), indent=2))

        return HttpResponse()
    elif operation == 'save_statistics':
        obj = json.loads(request.body, encoding='utf-8')
        total_stats = Statistics.from_json(obj)
        total_stats.to_json_file(page.file('statistics').local_path())

        # add to backup archive
        with zipfile.ZipFile(page.file('statistics_backup').local_path(), 'a', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('statistics_{}.json'.format(datetime.datetime.now()), json.dumps(total_stats.to_json(), indent=2))

        return HttpResponse()
    elif operation == 'save':
        obj = json.loads(request.body, encoding='utf-8')
        pcgts = PcGts.from_json(obj, page)
        pcgts.to_file(page.file('pcgts').local_path())

        # add to backup archive
        with zipfile.ZipFile(page.file('pcgts_backup').local_path(), 'a', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('pcgts_{}.json'.format(datetime.datetime.now()), json.dumps(pcgts.to_json(), indent=2))

        return HttpResponse()

    elif operation == 'clean':
        for key, _ in file_definitions.items():
            if key != 'color_original':
                File(page, key).delete()

        return HttpResponse()

    else:
        return HttpResponseBadRequest()


def get_page_progress(request, book, page):
    page = Page(Book(book), page)
    file = File(page, 'page_progress')

    if not file.exists():
        file.create()

    try:
        return JsonResponse(PageProgress.from_json_file(file.local_path()).to_json())
    except JSONDecodeError as e:
        logging.error(e)
        file.delete()
        file.create()
        return JsonResponse(PageProgress.from_json_file(file.local_path()).to_json())


def get_pcgts(request, book, page):
    page = Page(Book(book), page)
    file = File(page, 'pcgts')

    if not file.exists():
        file.create()

    try:
        return JsonResponse(PcGts.from_file(file).to_json())
    except JSONDecodeError as e:
        logging.error(e)
        file.delete()
        file.create()
        return JsonResponse(PcGts.from_file(file).to_json())


def get_statistics(request, book, page):
    page = Page(Book(book), page)
    file = File(page, 'statistics')

    if not file.exists():
        file.create()

    try:
        return JsonResponse(Statistics.from_json_file(file.local_path()).to_json())
    except JSONDecodeError as e:
        logging.error(e)
        file.delete()
        file.create()
        return JsonResponse(Statistics.from_json_file(file.local_path()).to_json())


def list_book(request, book):
    book = Book(book)
    pages = book.pages()
    return JsonResponse({'pages': sorted([{'label': page.page} for page in pages if page.is_valid()], key=lambda v: v['label'])})


@csrf_exempt
def new_book(request):
    if request.method != 'POST':
        return HttpResponseBadRequest()

    book = json.loads(request.body, encoding='utf-8')
    if 'name' not in book:
        return HttpResponseBadRequest()

    book_id = re.sub('[^\w]', '_', book['name'])

    from .book_meta import BookMeta
    try:
        b = Book(book_id)
        if b.exists():
            return HttpResponseNotModified()

        if b.create(BookMeta(id=b.book, name=book['name'])):
            return JsonResponse(b.get_meta().to_json())
    except InvalidFileNameException as e:
        logging.error(e)
        return HttpResponse(status=InvalidFileNameException.STATUS)

    return HttpResponseBadRequest()


@csrf_exempt
def delete_book(request):
    if request.method != 'POST':
        return HttpResponseBadRequest()

    jdata = json.loads(request.body, encoding='utf-8')
    if 'id' not in jdata:
        return HttpResponseBadRequest()

    book_id = jdata['id']
    book = Book(book_id)
    book.delete()

    return HttpResponse()



def list_all_books(request):
    # TODO: sort by in request
    books = Book.list_available_book_metas()
    return JsonResponse({'books': sorted([book.to_json() for book in books], key=lambda b: b['name'])})


def book_download(request, book, type):
    book = Book(book)
    if type == 'annotations.zip':
        import zipfile, io, os
        s = io.BytesIO()
        zf = zipfile.ZipFile(s, 'w')
        pages = book.pages()
        for page in pages:
            color_img = page.file('color_deskewed')
            binary_img = page.file('binary_deskewed')
            annotation = page.file('annotation')
            if not color_img.exists() or not binary_img.exists() or not annotation.exists():
                continue

            zf.write(color_img.local_path(), os.path.join('color', page.page + color_img.ext()))
            zf.write(binary_img.local_path(), os.path.join('binary', page.page + binary_img.ext()))
            zf.write(annotation.local_path(), os.path.join('annotation', page.page + annotation.ext()))

        zf.close()
        s.seek(0)
        return FileResponse(s, as_attachment=True, filename=book.book + '.zip')

    return HttpResponseBadRequest()



def index(request):
    return HttpResponse("Hello, world. You're at the polls index.")
