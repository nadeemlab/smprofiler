from typing import cast
from typing import Literal
import time
from pathlib import Path

from attrs import define
from numpy.random import Generator as RandomNumberGenerator
from numpy import arange as np_arange
from numpy import newaxis as np_newaxis
from numpy.typing import NDArray
from sklearn.metrics import mean_absolute_error
from sklearn.metrics import r2_score
from sklearn.model_selection import train_test_split

from smprofiler.atlas.reporting import format_elapsed
from smprofiler.atlas.reporting import section
from smprofiler.atlas.reporting import subsection
from smprofiler.atlas.reporting import report_model_stats
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.types import TrainingProgress
from smprofiler.atlas.types import Splits
from smprofiler.atlas.types import SelectedModel
from smprofiler.atlas.types import CellAtlasSource
from smprofiler.atlas.types import STD_METHODS
from smprofiler.atlas.extract_relevant_atlas import LoadFromExtraction
from smprofiler.atlas.model_selection_fitting import TREE_METHODS
from smprofiler.atlas.model_selection_fitting import ModelSelectionFitting
from smprofiler.atlas.artifacts import export_to_onnx
from smprofiler.atlas.artifacts import validate_onnx
from smprofiler.atlas.artifacts import write_metadata_to_file
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


ATLAS_VERSION = CellAtlasSource.ALLEN_IMMUNE_HEALTH.value


@define
class FeatureMatrices:
    x_identity_raw: NDArray
    x_identity: NDArray
    x_unscaled: NDArray
    x_valid_row_sums: NDArray


class TrainingStudy:
    options: TrainingOptions
    scenario: TrainingScenarioStudy
    rng: RandomNumberGenerator
    progress: TrainingProgress
    feature_matrices: FeatureMatrices
    _splits: Splits
    _selected: SelectedModel
    _tree_calibration: float | None

    def __init__(
        self,
        options: TrainingOptions,
        scenario: TrainingScenarioStudy,
        random_number_generator: RandomNumberGenerator,
        progress: TrainingProgress
    ):
        self.options = options
        self.scenario = scenario
        self.rng = random_number_generator
        self.progress = progress

    def train_models(
        self,
        total_models: int,
        total_studies: int,
        studies_index: int,
    ) -> None:
        study_name = self.scenario.study_handle
        section(
            f'[{studies_index}/{total_studies}] Study: {study_name}  '
            f'({len(self.scenario.get_channels('functional'))} models to train)'
        )
        logger.info('  Identity features : %s', self.scenario.get_channels_study_specific_strs('identity'))
        logger.info('  Functional targets: %s', self.scenario.get_channels_study_specific_strs('functional'))
        model_counter = 0
        ordinary_concordances = 0
        std_concordances = 0
        self._form_training_feature_matrices()
        targets = self.scenario.get_channels('functional')
        for index, channel in enumerate(targets):
            model_counter += 1
            subsection(
                f'Model [{model_counter + self.progress.model_counter}/{total_models}]  '
                f'study="{study_name}"  target="{channel.atlas_specific_name}"  '
                f'({index + 1}/{len(targets)} in study)'
            )
            self._train_model_one_marker(index, channel.study_specific_name)
            ordinary, std = self._validate_onnx()
            ordinary_concordances += 1 if ordinary else 0
            std_concordances += 1 if std else 0
        self.progress.model_counter += model_counter
        self.progress.number_validated += ordinary_concordances
        self.progress.number_validated_std += std_concordances

    def _train_model_one_marker(self, target_column: int, target_channel: str) -> None:
        self._form_splits(target_column, target_channel)
        self._train_and_select_best()
        self._export()

    def _form_training_feature_matrices(self) -> None:
        atlas_channels_for_training = list(map(lambda c: c.atlas_specific_name, self.scenario.channels))
        identity_only = list(map(lambda c: c.atlas_specific_name, self.scenario.get_channels('identity')))
        x_unfiltered_unscaled = LoadFromExtraction.load(
            self.options.parquet_atlas_path,
            atlas_channels_for_training,
            max_cells=self.options.max_cells,
            rng=self.rng,
        )
        x_identity_unscaled = x_unfiltered_unscaled[:, [i for i, name in enumerate(atlas_channels_for_training) if name in identity_only]]

        row_sums_all = x_identity_unscaled.sum(axis=1)
        valid_mask = row_sums_all > 1e-8
        n_zero_sum = int((~valid_mask).sum())
        if n_zero_sum:
            logger.info('  Removed %d cells with zero identity-channel sum', n_zero_sum)
        x_identity_raw = x_identity_unscaled[valid_mask]
        x_identity = x_identity_raw / row_sums_all[valid_mask, np_newaxis]
        x_unscaled = x_unfiltered_unscaled[valid_mask]

        self.feature_matrices = FeatureMatrices(
            x_identity_raw,
            x_identity,
            x_unscaled,
            row_sums_all[valid_mask],
        )

        logger.info(
            '  Normalized: %s cells retained  (%.2f%% of loaded)',
            f'{self.feature_matrices.x_identity.shape[0]:,}',
            100.0 * self.feature_matrices.x_identity.shape[0] / x_unfiltered_unscaled.shape[0],
        )

    def _form_splits(self, target_column: int, target_channel: str) -> None:
        y = self.feature_matrices.x_unscaled[:, target_column] / self.feature_matrices.x_valid_row_sums

        if y.std() < 1e-6:
            logger.warning("Skipping: target '%s' has near-zero variance", target_channel)
            return False, False

        logger.info('  Features : %d identity markers, %s cells (after S>0 filter)', self.feature_matrices.x_identity.shape[1], f'{self.feature_matrices.x_identity.shape[0]:,}')
        logger.info('  Target   : "%s" (norm; range %.4f - %.4f, mean %.4f)', target_channel, float(y.min()), float(y.max()), float(y.mean()))

        train_indices, test_indices = cast(tuple[NDArray, NDArray], train_test_split(
            np_arange(len(y)), test_size=0.2, random_state=42
        ))
        x = self.feature_matrices.x_identity
        x_train, x_test = x[train_indices], x[test_indices]
        y_train, y_test = y[train_indices], y[test_indices]
        logger.info('  Split    : %s train / %s test', f'{len(x_train):,}', f'{len(x_test):,}')
        self._splits = Splits(test_indices, x_train, x_test, y_train, y_test, target_channel)

    def _train_and_select_best(self) -> str:
        t_train_start = time.monotonic()
        best_name, best_model, cv_r2, cv_r2_std = ModelSelectionFitting.train_and_select_best(
            self._splits.x_train, self._splits.y_train, cv_folds=self.options.cv_folds
        )
        train_seconds = time.monotonic() - t_train_start
        train_elapsed = format_elapsed(train_seconds)

        y_pred_mean, y_pred_std = ModelSelectionFitting.predict_with_std(best_model, best_name, self._splits.x_test)
        test_r2 = float(r2_score(self._splits.y_test, y_pred_mean))
        test_mae = float(mean_absolute_error(self._splits.y_test, y_pred_mean))
        residuals = self._splits.y_test - y_pred_mean
        global_std = float(residuals.std())

        self._selected = SelectedModel(best_model, best_name, cv_r2, cv_r2_std, train_elapsed, train_seconds, test_r2, test_mae, global_std)
        self._tree_calibration = self._get_tree_calibration()
        report_model_stats(self._selected)

    def _validate(self) -> tuple[bool, bool]:
        n_validate = min(500, len(self._splits.test_indices))
        validation_indices = self._splits.test_indices[:n_validate]
        ordinary, std = validate_onnx(
            self._get_onnx_model_path(),
            self._selected.model,
            self._selected.name,
            self.feature_matrices.x_identity_raw[validation_indices],
            self.feature_matrices.x_unscaled[validation_indices, self._splits.target_column],
            double_precision=False,
            tree_calibration=self._tree_calibration,
        )
        return ordinary, std

    def _get_tree_calibration(self) -> float | None:
        y_pred_mean, y_pred_std = ModelSelectionFitting.predict_with_std(self._selected.model, self._selected.name, self._splits.x_test)
        residuals = self._splits.y_test - y_pred_mean
        tree_calibration = None
        if self._selected.name in TREE_METHODS:
            tree_calibration = ModelSelectionFitting.tree_std_calibration(residuals, y_pred_std)
            logger.info('  Tree spread calibration = %.4f', tree_calibration)
        return tree_calibration

    def _export(self) -> None:
        export_to_onnx(
            self._selected.model,
            self._selected.name,
            self.feature_matrices.x_identity.shape[1],
            self._get_onnx_model_path(),
            double_precision=False,
            tree_calibration=self._tree_calibration,
        )

        write_metadata_to_file(
            self._get_onnx_metadata_path(),
            study=self.scenario.study_handle,
            target_channel=self._splits.target_channel,
            input_channels=self.scenario.get_channels_study_specific_strs('identity'),
            model_type=self._selected.name,
            cv_r2=self._selected.cv_r2,
            cv_r2_std=self._selected.cv_r2_std,
            test_r2=self._selected.test_r2,
            test_mae=self._selected.test_mae,
            n_train=len(self._splits.x_train),
            n_test=len(self._splits.x_test),
            atlas_version=ATLAS_VERSION,
            sum_normalized=True,
            std_method=STD_METHODS[self._selected.name],
            global_std=self._selected.global_std,
            onnx_input_dtype='float32',
            onnx_has_std=True,
            tree_calibration=self._tree_calibration,
        )

        self.progress.summary_rows.append({
            'study': self.scenario.study_handle,
            'target': self._splits.target_channel,
            'model': self._selected.name,
            'std_method': STD_METHODS[self._selected.name],
            'cv_R²': self._selected.cv_r2,
            'test_R²': self._selected.test_r2,
            'test_MAE': self._selected.test_mae,
            'onnx_kb': self._get_onnx_model_path().stat().st_size // 1024,
        })

        if self.options.database_config_file is not None:
            self.progress.model_records.append({
                'study': self.scenario.study_handle,
                'target_channel': self._splits.target_channel,
                'input_channels': self.scenario.get_channels_study_specific_strs('identity'),
                'architecture_type': self._seleced.name,
                'std_method': STD_METHODS[self._selected.name],
                'onnx_input_dtype': 'float32',
                'onnx_has_std': True,
                'atlas_version': ATLAS_VERSION,
                'cv_r2': self._selected.cv_r2,
                'test_r2': self._selected.test_r2,
                'test_mae': self._selected.test_mae,
                'n_train': len(self._splits.x_train),
                'n_test': len(self._splits.x_test),
                'training_time_seconds': self._selected.train_seconds,
                'onnx_bytes': self._get_onnx_model_path().read_bytes(),
            })

    def _get_onnx_model_path(self) -> Path:
        return self._get_onnx_file_path('model')

    def _get_onnx_metadata_path(self) -> Path:
        return self._get_onnx_file_path('metadata')

    def _get_onnx_file_path(self, contents: Literal['model', 'metadata']) -> Path:
        safe_target = self._splits.target_channel.replace('/', '_').replace(' ', '_')
        study_out_dir = self.options.output_directory / self.scenario.study_handle
        if contents == 'model':
            return study_out_dir / f'{safe_target}.onnx'
        if contents == 'metadata':
            return study_out_dir / f'{safe_target}.meta.json'

