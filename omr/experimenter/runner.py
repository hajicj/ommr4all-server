import logging
import sys

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    stream=sys.stdout)

import os

from pagesegmentation.lib.model import Architecture

from omr.adapters.pagesegmentation.params import PageSegmentationTrainerParams
from omr.steps.algorithmpreditorparams import AlgorithmPredictorParams, SerializableCTCDecoderParams
from omr.steps.algorithmtrainerparams import AlgorithmTrainerParams
from omr.steps.symboldetection.sequencetosequence.params import CalamariParams
import django
os.environ['DJANGO_SETTINGS_MODULE'] = 'ommr4all.settings'
django.setup()

from omr.dataset import DatasetParams, LyricsNormalization
from omr.steps.algorithmtypes import AlgorithmTypes
from omr.dataset.dataset import LyricsNormalizationParams
from calamari_ocr.proto import CTCDecoderParams
import numpy as np

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    import argparse
    import random
    from omr.experimenter.experimenter import GlobalDataArgs, EvaluatorParams, ExperimenterScheduler

    parser = argparse.ArgumentParser()
    parser.add_argument('--magic_prefix', default='EXPERIMENT_OUT=')
    parser.add_argument("--train", default=None, nargs="+")
    parser.add_argument("--test", default=None, nargs="+")
    parser.add_argument("--train_extend", default=None, nargs="+")
    parser.add_argument("--model_dir", type=str, default="model_out")
    parser.add_argument("--cross_folds", type=int, default=5)
    parser.add_argument("--single_folds", type=int, default=[0], nargs="+")
    parser.add_argument("--skip_train", action="store_true")
    parser.add_argument("--skip_predict", action="store_true")
    parser.add_argument("--skip_eval", action="store_true")
    parser.add_argument("--cleanup", action="store_true", default=False)
    parser.add_argument("--n_train", default=-1, type=int)
    parser.add_argument("--n_iter", default=-1, type=int)
    parser.add_argument("--val_amount", default=0.2, type=float)
    parser.add_argument("--pretrained_model", default=None, type=str)
    parser.add_argument("--data_augmentation", action="store_true")
    parser.add_argument("--data_augmentation_factor", type=float, default=0)
    parser.add_argument("--output_book", default=None, type=str)
    parser.add_argument("--type", type=lambda t: AlgorithmTypes[t], required=True, choices=list(AlgorithmTypes))
    parser.add_argument("--early_stopping_at_accuracy", type=float, default=0)
    parser.add_argument("--early_stopping_max_keep", type=int, default=-1)
    parser.add_argument("--train_data_multiplier", type=int, default=1)

    parser.add_argument("--height", type=int, default=80)
    parser.add_argument("--pad", type=int, default=[0], nargs="+")
    parser.add_argument("--pad_to_power_of_2", type=int, default=None)
    parser.add_argument("--center", action='store_true')
    parser.add_argument("--cut_region", action='store_true')
    parser.add_argument("--dewarp", action='store_true')
    parser.add_argument("--use_regions", action="store_true", default=False)
    parser.add_argument("--neume_types", action="store_true", default=False)
    parser.add_argument("--gray", action="store_true")
    parser.add_argument("--full_page", action="store_true")
    parser.add_argument("--extract_region_only", action="store_true")
    parser.add_argument("--gt_line_thickness", default=3, type=int)
    parser.add_argument("--min_number_of_staff_lines", default=4, type=int)
    parser.add_argument("--max_number_of_staff_lines", default=4, type=int)

    parser.add_argument("--page_segmentation_architecture", type=lambda t: Architecture[t], choices=list(Architecture), default=PageSegmentationTrainerParams().architecture)
    parser.add_argument("--lyrics_normalization", type=lambda t: LyricsNormalization[t], choices=list(LyricsNormalization), default=DatasetParams().lyrics_normalization.lyrics_normalization)
    parser.add_argument("--lyrics_mixed_case", action='store_true')

    parser.add_argument("--calamari_n_folds", type=int, default=0)
    parser.add_argument("--calamari_single_folds", type=int, nargs='+')
    parser.add_argument("--calamari_network", type=str, default='cnn=40:3x3,pool=2x2,cnn=60:3x3,pool=2x2,lstm=200,dropout=0.5')
    parser.add_argument("--calamari_channels", type=int, default=1)
    parser.add_argument("--calamari_ctc_decoder", type=str, choices=[CTCDecoderParams.CTCDecoderType.Name(x) for x in CTCDecoderParams.CTCDecoderType.values()], default=CTCDecoderParams.CTCDecoderType.Name(AlgorithmPredictorParams().ctcDecoder.params.type))
    parser.add_argument("--calamari_ctc_decoder_beam_width", type=int, default=AlgorithmPredictorParams().ctcDecoder.params.beam_width)
    parser.add_argument("--calamari_ctc_dictionary_from_gt", action='store_true')

    # evaluation parameters
    parser.add_argument("--seed", type=int, default=1)

    # evaluation params
    parser.add_argument("--symbol_detected_min_distance", type=int, default=EvaluatorParams().symbol_detected_min_distance)
    parser.add_argument("--staff_line_found_distance", default=EvaluatorParams().staff_line_found_distance, type=int)
    parser.add_argument("--line_hit_overlap_threshold", default=EvaluatorParams().line_hit_overlap_threshold, type=float)
    parser.add_argument("--staff_n_lines_threshold", default=EvaluatorParams().staff_line_found_distance, type=int)

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)

    if not args.use_regions and args.cut_region:
        logger.warning("Cannot bot set 'cut_region' and 'staff_lines_only'. Setting 'cut_region=False'")
        args.cut_region = False

    global_args = GlobalDataArgs(
        args.magic_prefix,
        args.model_dir,
        args.cross_folds,
        args.single_folds,
        args.skip_train,
        args.skip_predict,
        args.skip_eval,
        not args.cleanup,
        DatasetParams(
            gt_required=True,
            height=args.height,
            pad=list(args.pad),
            center=args.center,
            cut_region=args.cut_region,
            dewarp=args.dewarp,
            staff_lines_only=not args.use_regions,
            pad_power_of_2=args.pad_to_power_of_2,
            neume_types_only=args.neume_types,

            full_page=args.full_page,
            gray=args.gray,
            extract_region_only=args.extract_region_only,
            gt_line_thickness=args.gt_line_thickness,

            lyrics_normalization=LyricsNormalizationParams(
                args.lyrics_normalization,
                not args.lyrics_mixed_case,
            ),
        ),
        evaluation_params=EvaluatorParams(
            symbol_detected_min_distance=args.symbol_detected_min_distance,

            staff_line_found_distance=args.staff_line_found_distance,
            line_hit_overlap_threshold=args.line_hit_overlap_threshold,
            staff_n_lines_threshold=args.staff_n_lines_threshold,
        ),
        predictor_params=AlgorithmPredictorParams(
            minNumberOfStaffLines=args.min_number_of_staff_lines,
            maxNumberOfStaffLines=args.max_number_of_staff_lines,
            ctcDecoder=SerializableCTCDecoderParams(
                type=CTCDecoderParams.CTCDecoderType.Value(args.calamari_ctc_decoder),
                beam_width=args.calamari_ctc_decoder_beam_width,
            )
        ),
        output_book=args.output_book,
        algorithm_type=args.type,
        trainer_params=AlgorithmTrainerParams(
            n_iter=args.n_iter,
            display=100,
            load=args.pretrained_model,
            processes=8,
            early_stopping_at_acc=args.early_stopping_at_accuracy,
            early_stopping_max_keep=args.early_stopping_max_keep,
            train_data_multiplier=args.train_data_multiplier,
            data_augmentation_factor=args.data_augmentation_factor,
        ),
        page_segmentation_params=PageSegmentationTrainerParams(
            data_augmentation=args.data_augmentation,
            architecture=args.page_segmentation_architecture,
        ),
        calamari_params=CalamariParams(
            network=args.calamari_network,
            n_folds=args.calamari_n_folds,
            single_folds=args.calamari_single_folds,
            channels=args.calamari_channels,
        ),
        calamari_dictionary_from_gt=args.calamari_ctc_dictionary_from_gt
    )

    experimenter = ExperimenterScheduler(global_args)
    experimenter.run(
        args.n_train,
        args.val_amount,
        args.cross_folds,
        args.single_folds,
        args.train,
        args.test,
        args.train_extend,
    )
