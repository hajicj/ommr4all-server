import os
if __name__ == '__main__':
    import django
    os.environ['DJANGO_SETTINGS_MODULE'] = 'ommr4all.settings'
    django.setup()

from calamari_ocr.proto import CheckpointParams, DataPreprocessorParams, TextProcessorParams, network_params_from_definition_string
from calamari_ocr.ocr.trainer import Trainer
from calamari_ocr.ocr.cross_fold_trainer import CrossFoldTrainer
from calamari_ocr.ocr.augmentation import SimpleDataAugmenter
from typing import List, Optional
from database.file_formats import PcGts
from database import DatabaseBook
from omr.dataset import DatasetParams
from omr.steps.algorithm import AlgorithmTrainer, TrainerCallback, AlgorithmTrainerParams, AlgorithmTrainerSettings
from omr.imageoperations.music_line_operations import SymbolLabel
from omr.steps.symboldetection.sequencetosequence.meta import Meta

from database.file_formats.performance.pageprogress import Locks
from omr.steps.symboldetection.sequencetosequence.params import CalamariParams


class OMRTrainer(AlgorithmTrainer):
    @staticmethod
    def meta() -> Meta.__class__:
        return Meta

    @staticmethod
    def default_params() -> AlgorithmTrainerParams:
        return AlgorithmTrainerParams(
            n_iter=10_000,
            l_rate=1e-3,
            display=100,
            early_stopping_test_interval=1000,
            early_stopping_max_keep=5,
            processes=1,
        )

    @staticmethod
    def default_dataset_params() -> DatasetParams:
        return DatasetParams(
            pad=[0, 10, 0, 40],
            cut_region=False,
        )

    @staticmethod
    def force_dataset_params(params: DatasetParams):
        params.dewarp = True
        params.center = True
        params.staff_lines_only = True
        params.pad_power_of_2 = False

    def __init__(self, params: AlgorithmTrainerSettings):
        super().__init__(params)
        if not params.dataset_params.staff_lines_only:
            raise ValueError("Calamari S2S training must be performed on staves only. Set dataset param staff_lines_only to True")

        # if not params.train_data.params.center or not params.validation_data.params.center:
        #    raise ValueError("Calamari S2S training must be performed on centered staves only. Set dataset param center to True")

    def _train(self, target_book: Optional[DatabaseBook] = None, callback: Optional[TrainerCallback] = None):
        if callback:
            callback.resolving_files()

        train_dataset = self.train_dataset.to_calamari_dataset(train=True, callback=callback)
        val_dataset = self.validation_dataset.to_calamari_dataset(train=True, callback=callback)

        params = CheckpointParams()

        params.max_iters = self.params.n_iter
        params.stats_size = 1000
        params.batch_size = 1
        params.checkpoint_frequency = 0
        params.output_dir = self.settings.model.path
        params.output_model_prefix = 'omr'
        params.display = self.params.display
        params.skip_invalid_gt = True
        params.processes = -1
        params.data_aug_retrain_on_original = True

        params.early_stopping_frequency = self.params.early_stopping_test_interval
        params.early_stopping_nbest = self.params.early_stopping_max_keep
        params.early_stopping_best_model_prefix = 'omr_best'
        params.early_stopping_best_model_output_dir = self.settings.model.path

        params.model.data_preprocessor.type = DataPreprocessorParams.NOOP_NORMALIZER
        # for preproc in [DataPreprocessorParams.RANGE_NORMALIZER, DataPreprocessorParams.FINAL_PREPARATION]:
        #    pp = params.model.data_preprocessor.children.add()
        #    pp.type = preproc
        params.model.text_preprocessor.type = TextProcessorParams.NOOP_NORMALIZER
        params.model.text_postprocessor.type = TextProcessorParams.NOOP_NORMALIZER

        params.model.line_height = self.settings.dataset_params.height
        params.model.network.channels = self.settings.calamari_params.channels

        network_str = self.settings.calamari_params.network
        if self.params.l_rate > 0:
            network_str += ',learning_rate={}'.format(self.params.l_rate)

        if self.settings.calamari_params.n_folds > 0:
            train_args = {
                "max_iters": params.max_iters,
                "stats_size": params.stats_size,
                "checkpoint_frequency": params.checkpoint_frequency,
                "pad": 0,
                "network": network_str,
                "early_stopping_frequency": params.early_stopping_frequency,
                "early_stopping_nbest": params.early_stopping_nbest,
                "line_height": params.model.line_height,
                "data_preprocessing": ["RANGE_NORMALIZER", "FINAL_PREPARATION"],
            }
            trainer = CrossFoldTrainer(
                self.settings.calamari_params.n_folds, train_dataset,
                params.output_dir, 'omr_best_{id}', train_args, progress_bars=True
            )
            temporary_dir = os.path.join(params.output_dir, "temporary_dir")
            trainer.run(
                self.settings.calamari_params.single_folds,
                temporary_dir=temporary_dir,
                spawn_subprocesses=False, max_parallel_models=1,    # Force to run in same scope as parent process
            )
        else:
            network_params_from_definition_string(network_str, params.model.network)
            trainer = Trainer(
                checkpoint_params=params,
                dataset=train_dataset,
                validation_dataset=val_dataset,
                n_augmentations=0,
                data_augmenter=SimpleDataAugmenter(),
                weights=self.params.load,
                preload_training=True,
                preload_validation=True,
            )
            trainer.train()


if __name__ == '__main__':
    import random
    import numpy as np
    random.seed(1)
    np.random.seed(1)
    b = DatabaseBook('Graduel_Fully_Annotated')
    from omr.dataset.datafiles import dataset_by_locked_pages, LockState
    train_pcgts, val_pcgts = dataset_by_locked_pages(0.8, [LockState(Locks.SYMBOLS, True), LockState(Locks.LAYOUT, True)], True, [b])
    dataset_params = DatasetParams(
        gt_required=True,
        height=40,
        dewarp=True,
        cut_region=False,
        pad=[0, 10, 0, 20],
        center=True,
        staff_lines_only=True,
        masks_as_input=False,
    )
    train_settings = AlgorithmTrainerSettings(
        dataset_params=dataset_params,
        train_data=train_pcgts,
        validation_data=val_pcgts,
        params=AlgorithmTrainerParams(
            l_rate=1e-3,
        ),
        calamari_params=CalamariParams(
            network='cnn=40:3x3,pool=1x2,cnn=80:3x3,lstm=100,dropout=0.5',
            n_folds=0,
            channels=1,
        )
    )
    trainer = OMRTrainer(train_settings)
    trainer.train(b)



