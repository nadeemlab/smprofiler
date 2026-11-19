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
from smprofiler.atlas.artifacts import SklearnToONNX
from smprofiler.atlas.artifacts import SklearnToONNXValidation
from smprofiler.atlas.artifacts import write_metadata_to_file
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


ATLAS_VERSION = CellAtlasSource.ALLEN_IMMUNE_HEALTH.value


@define
class FeatureMatrices:
    reference_cell_data: NDArray
    reference_cell_data_identity: NDArray
    reference_cell_data_identity_normalized: NDArray
    row_sums: NDArray


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
            if not self._train_model_one_marker(index, channel.study_specific_name):
                continue
            ordinary, std = self._validate_onnx()
            ordinary_concordances += 1 if ordinary else 0
            std_concordances += 1 if std else 0
            self._cleanup_training_state()
        self.progress.model_counter += model_counter
        self.progress.number_validated += ordinary_concordances
        self.progress.number_validated_std += std_concordances

    def _train_model_one_marker(self, target_column: int, target_channel: str) -> bool:
        if not self._form_splits(target_column, target_channel):
            logger.warning('Something went wrong forming cross validation split.')
            return False
        self._train_and_select_best_model()
        self._export()
        return True

    def _form_training_feature_matrices(self) -> None:
        _reference_cell_data, _reference_cell_data_identity = self._load_from_extraction()
        (
            reference_cell_data,
            reference_cell_data_identity,
            row_sums,
        ) = self._restrict_to_nontrivial(_reference_cell_data, _reference_cell_data_identity)
        reference_cell_data_identity_normalized = self._normalized_feature_matrix(reference_cell_data_identity, row_sums)
        self.feature_matrices = FeatureMatrices(
            reference_cell_data,
            reference_cell_data_identity,
            reference_cell_data_identity_normalized,
            row_sums,
        )

    def _load_from_extraction(self) -> tuple[NDArray, NDArray]:
        atlas_channels_for_training = list(map(lambda c: c.atlas_specific_name, self.scenario.channels))
        identity_only = list(map(lambda c: c.atlas_specific_name, self.scenario.get_channels('identity')))
        _reference_cell_data = LoadFromExtraction.load(
            self.options.parquet_atlas_path,
            atlas_channels_for_training,
            max_cells=self.options.max_cells,
            rng=self.rng,
        )
        identity_indices = [i for i, name in enumerate(atlas_channels_for_training) if name in identity_only]
        _reference_cell_data_identity = _reference_cell_data[:, identity_indices]
        return _reference_cell_data, _reference_cell_data_identity

    def _restrict_to_nontrivial(self, _reference_cell_data, _reference_cell_data_identity) -> tuple[NDArray, NDArray, NDArray]:
        _row_sums = _reference_cell_data_identity.sum(axis=1)
        valid_mask = _row_sums > 1e-8
        number_zero_sum = int((~valid_mask).sum())
        if number_zero_sum:
            logger.info('Removed %d cells with zero identity-channel sum', number_zero_sum)
        reference_cell_data = _reference_cell_data[valid_mask]
        reference_cell_data_identity = _reference_cell_data_identity[valid_mask]
        row_sums = _row_sums[valid_mask]
        return reference_cell_data, reference_cell_data_identity, row_sums

    def _normalized_feature_matrix(self, reference_cell_data_identity: NDArray, row_sums: NDArray) -> NDArray:
        reference_cell_data_identity_normalized = reference_cell_data_identity / row_sums[:, np_newaxis]
        logger.info(
            'Features : %d identity markers, %s cells (after sum>0 filter)',
            reference_cell_data_identity_normalized.shape[1],
            f'{reference_cell_data_identity_normalized.shape[0]}',
        )
        return reference_cell_data_identity_normalized

    def _form_splits(self, target_column: int, target_channel: str) -> bool:
        x = self.feature_matrices.reference_cell_data_identity_normalized
        y = self.feature_matrices.reference_cell_data[:, target_column] / self.feature_matrices.row_sums

        if y.std() < 1e-6:
            logger.warning("Skipping: target '%s' has near-zero variance", target_channel)
            self._cleanup_training_state()
            return False

        logger.info(
            '  Target   : "%s" (norm; range %.4f - %.4f, mean %.4f)',
            target_channel,
            float(y.min()),
            float(y.max()),
            float(y.mean()),
        )

        train_indices, test_indices = cast(tuple[NDArray, NDArray], train_test_split(
            np_arange(len(y)), test_size=0.2, random_state=42
        ))
        x_train, x_test = x[train_indices], x[test_indices]
        y_train, y_test = y[train_indices], y[test_indices]
        logger.info('  Split    : %s train / %s test', f'{len(x_train):,}', f'{len(x_test):,}')
        self._splits = Splits(test_indices, x_train, x_test, y_train, y_test, target_channel, target_column)
        return True

    def _train_and_select_best_model(self) -> str:
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

    def _validate_onnx(self) -> tuple[bool, bool]:
        n_validate = min(500, len(self._splits.test_indices))
        validation_indices = self._splits.test_indices[:n_validate]
        ordinary, std = SklearnToONNXValidation.validate_onnx(
            self._get_onnx_model_path(),
            self._selected.model,
            self._selected.name,
            self.feature_matrices.reference_cell_data_identity[validation_indices],
            self.feature_matrices.reference_cell_data[validation_indices, self._splits.target_column],
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
        SklearnToONNX.export_to_onnx(
            self._selected.model,
            self._selected.name,
            self.feature_matrices.reference_cell_data_identity_normalized.shape[1],
            self._get_onnx_model_path(),
            double_precision=False,
            tree_calibration=self._tree_calibration,
        )
        metadata = {
            'study': self.scenario.study_handle,
            'target_channel': self._splits.target_channel,
            'input_channels': self.scenario.get_channels_study_specific_strs('identity'),
            'architecture_type': self._selected.name,
            'cv_r2': self._selected.cv_r2,
            'cv_r2_std': self._selected.cv_r2_std,
            'test_r2': self._selected.test_r2,
            'test_mae': self._selected.test_mae,
            'n_train': len(self._splits.x_train),
            'n_test': len(self._splits.x_test),
            'atlas_version': ATLAS_VERSION,
            'std_method': STD_METHODS[self._selected.name],
            'onnx_input_dtype': 'float32',
            'onnx_has_std': True,
        }
        write_metadata_to_file(
            self._get_onnx_metadata_path(),
            **metadata,
            sum_normalized=True,
            global_std=self._selected.global_std,
            tree_calibration=self._tree_calibration,
        )
        if self.options.database_config_file is not None:
            self.progress.model_records.append(metadata | {
                'onnx_bytes': self._get_onnx_model_path().read_bytes(),
                'training_time_seconds': self._selected.training_time_seconds,
            })
        summary_keys = ['study', 'target_channel', 'architecture_type', 'std_method', 'cv_r2', 'test_r2', 'test_mae']
        self.progress.summary_rows.append(
            {k: metadata[k] for k in summary_keys} | {
                'onnx_kb': self._get_onnx_model_path().stat().st_size // 1024,
            }
        )

    def _cleanup_training_state(self) -> None:
        self._splits = None
        self._selected = None
        self._tree_calibration = None

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

