from calamari_ocr.ocr.callbacks import TrainingCallback
from calamari_ocr.proto import CheckpointParams, DataPreprocessorParams, TextProcessorParams, network_params_from_definition_string
from calamari_ocr.ocr.trainer import Trainer
from calamari_ocr.ocr.cross_fold_trainer import CrossFoldTrainer
from calamari_ocr.ocr.augmentation import SimpleDataAugmenter
from typing import Optional, Type

from database.file_formats.performance.pageprogress import Locks
from omr.dataset import DatasetParams, LyricsNormalization
from omr.steps.symboldetection.sequencetosequence.params import CalamariParams
from database import DatabaseBook
import os

from omr.steps.algorithm import AlgorithmTrainerParams, AlgorithmTrainerSettings, TrainerCallback, AlgorithmMeta
from omr.steps.text.trainer import TextTrainerBase


class CalamariTrainerCallback(TrainingCallback):
    def __init__(self, cb: TrainerCallback):
        self.cb = cb

    def display(self, train_cer, train_loss, train_dt, iter, steps_per_epoch, display_epochs,
                example_pred, example_gt):
        self.cb.next_iteration(iter, train_loss, 1 - train_cer)

    def early_stopping(self, eval_cer, n_total, n_best, iter):
        self.cb.next_best_model(iter, eval_cer, n_best - 1)


class CalamariTrainer(TextTrainerBase):
    @staticmethod
    def meta() -> Type['AlgorithmMeta']:
        from omr.steps.text.calamari.meta import Meta
        return Meta

    @staticmethod
    def default_params() -> AlgorithmTrainerParams:
        return AlgorithmTrainerParams(
            n_iter=100_000,
            l_rate=1e-3,
            display=100,
            early_stopping_test_interval=1000,
            early_stopping_max_keep=5,
            processes=1,
            data_augmentation_factor=20,
        )

    @staticmethod
    def force_dataset_params(params: DatasetParams):
        params.height = 48

    def __init__(self, settings: AlgorithmTrainerSettings):
        settings.calamari_params.network = 'cnn=40:3x3,pool=2x2,cnn=60:3x3,pool=2x2,lstm=200,dropout=0.5'
        super().__init__(settings)

    def _train(self, target_book: Optional[DatabaseBook] = None, callback: Optional[TrainerCallback] = None):
        if callback:
            callback.resolving_files()
            calamari_callback = CalamariTrainerCallback(callback)
        else:
            calamari_callback = None

        train_dataset = self.train_dataset.to_text_line_calamari_dataset(train=True, callback=callback)
        val_dataset = self.validation_dataset.to_text_line_calamari_dataset(train=True, callback=callback)
        output = self.settings.model.path

        params = CheckpointParams()

        params.max_iters = self.params.n_iter
        params.stats_size = 1000
        params.batch_size = 1
        params.checkpoint_frequency = 0
        params.output_dir = output
        params.output_model_prefix = 'text'
        params.display = self.params.display
        params.skip_invalid_gt = True
        params.processes = 2
        params.data_aug_retrain_on_original = True

        params.early_stopping_at_acc = self.params.early_stopping_at_acc if self.params.early_stopping_at_acc else 0
        params.early_stopping_frequency = self.params.early_stopping_test_interval
        params.early_stopping_nbest = self.params.early_stopping_max_keep
        params.early_stopping_best_model_prefix = 'text_best'
        params.early_stopping_best_model_output_dir = output

        params.model.data_preprocessor.type = DataPreprocessorParams.DEFAULT_NORMALIZER
        params.model.data_preprocessor.pad = 5
        params.model.data_preprocessor.line_height = self.settings.dataset_params.height
        params.model.text_preprocessor.type = TextProcessorParams.NOOP_NORMALIZER
        params.model.text_postprocessor.type = TextProcessorParams.NOOP_NORMALIZER

        params.model.line_height = self.settings.dataset_params.height

        network_str = self.settings.calamari_params.network
        if self.params.l_rate > 0:
            network_str += ',learning_rate={}'.format(self.params.l_rate)

        if self.settings.calamari_params.n_folds > 1:
            train_args = {
                "max_iters": params.max_iters,
                "stats_size": params.stats_size,
                "checkpoint_frequency": params.checkpoint_frequency,
                "pad": 0,
                "network": network_str,
                "early-stopping_at_accuracy": params.early_stopping_at_acc,
                "early_stopping_frequency": params.early_stopping_frequency,
                "early_stopping_nbest": params.early_stopping_nbest,
                "line_height": params.model.line_height,
                "data_preprocessing": ["RANGE_NORMALIZER", "FINAL_PREPARATION"],
            }
            trainer = CrossFoldTrainer(
                self.settings.calamari_params.n_folds, train_dataset,
                output, 'omr_best_{id}', train_args, progress_bars=True
            )
            temporary_dir = os.path.join(output, "temporary_dir")
            trainer.run(
                self.settings.calamari_params.single_folds,
                temporary_dir=temporary_dir,
                spawn_subprocesses=False, max_parallel_models=1,    # Force to run in same scope as parent process
            )
        else:
            network_params_from_definition_string(network_str, params.model.network)
            trainer = Trainer(
                codec_whitelist='abcdefghijklmnopqrstuvwxyz ',      # Always keep space and all letters
                checkpoint_params=params,
                dataset=train_dataset,
                validation_dataset=val_dataset,
                n_augmentations=self.params.data_augmentation_factor if self.params.data_augmentation_factor else 0,
                data_augmenter=SimpleDataAugmenter(),
                weights=None if not self.params.model_to_load() else self.params.model_to_load().local_file('text_best.ckpt'),
                preload_training=True,
                preload_validation=True,
            )
            trainer.train(training_callback=calamari_callback,
                          auto_compute_codec=True,
                          )


if __name__ == '__main__':
    import random
    import numpy as np
    random.seed(1)
    np.random.seed(1)
    b = DatabaseBook('Graduel_Fully_Annotated')
    from omr.dataset.datafiles import dataset_by_locked_pages, LockState
    train_pcgts, val_pcgts = dataset_by_locked_pages(0.8, [LockState(Locks.LAYOUT, True)], True, [b])

    trainer_params = CalamariTrainer.default_params()
    trainer_params.l_rate = 1e-3
    trainer_params.load = '/home/ls6/wick/Documents/Projects/calamari_models/fraktur_historical_ligs/0.ckpt.json'

    params = DatasetParams(
        gt_required=True,
        height=48,
        cut_region=True,
        pad=[0, 10, 0, 20],
        lyrics_normalization=LyricsNormalization.ONE_STRING,
    )
    train_params = AlgorithmTrainerSettings(
        params,
        train_pcgts,
        val_pcgts,
        params=trainer_params,
        calamari_params=CalamariParams(
            network="cnn=40:3x3,pool=2x2,cnn=60:3x3,pool=2x2,lstm=200,dropout=0.5",
            n_folds=1,
        )
    )
    trainer = CalamariTrainer(train_params)
    trainer.train(b)



