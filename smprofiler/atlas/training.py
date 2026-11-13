from typing import cast
import time

from numpy.random import Generator as RandomNumberGenerator
from numpy import arange as np_arange
from numpy import newaxis as np_newaxis
from numpy.typing import NDArray
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from smprofiler.atlas.types import CellAtlasSource
from smprofiler.atlas.reporting import format_elapsed
from smprofiler.atlas.reporting import section
from smprofiler.atlas.reporting import subsection
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import TrainingScenarioStudy
from smprofiler.atlas.atlas_data import load_atlas_subset
from smprofiler.atlas.model_selection_fitting import STD_METHODS
from smprofiler.atlas.model_selection_fitting import TREE_METHODS
from smprofiler.atlas.model_selection_fitting import build_model_candidates
from smprofiler.atlas.model_selection_fitting import predict_with_std
from smprofiler.atlas.model_selection_fitting import train_and_select_best
from smprofiler.atlas.model_selection_fitting import _tree_std_calibration
from smprofiler.atlas.artifacts import export_to_onnx, validate_onnx, write_metadata_to_file
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


ATLAS_VERSION = CellAtlasSource.ALLEN_IMMUNE_HEALTH.value

class TrainingStudy:
    options: TrainingOptions
    rng: RandomNumberGenerator

    def __init__(self, options: TrainingOptions, random_number_generator: RandomNumberGenerator):
        self.options = options
        self.rng = random_number_generator

    def train_models(
        self,
        scenario: TrainingScenarioStudy,
        total_models: int,
        total_studies: int,
        summary_rows: list[dict],
        model_records: list[dict],
        plan_step: int,
        number_trained: int,
    ) -> tuple[int, int, int]:
        study_name = scenario.study_handle
        id_in_atlas = list(c.atlas_specific_name for c in scenario.get_channels('identity'))
        fn_in_atlas = list(c.atlas_specific_name for c in scenario.get_channels('functional'))
        final_channel_names = list(c.study_specific_name for c in scenario.get_channels('identity'))
        final_target_channel_names = list(c.study_specific_name for c in scenario.get_channels('functional'))

        section(
            f'[{plan_step}/{total_studies}] Study: {study_name}  '
            f'({len(fn_in_atlas)} models to train)'
        )
        logger.info('  Identity features : %s', id_in_atlas)
        logger.info('  Functional targets: %s', fn_in_atlas)

        if len(set(id_in_atlas).intersection(fn_in_atlas)) > 0:
            raise ValueError(f'Functional markers overlap with identity markers: {fn_in_atlas}; {id_in_atlas}')
        atlas_channels_for_training = id_in_atlas + fn_in_atlas
        smprofiler_channels = final_channel_names + final_target_channel_names

        X_unfiltered_unscaled = load_atlas_subset(
            self.options.parquet_atlas_path,
            atlas_channels_for_training,
            max_cells=self.options.max_cells,
            rng=self.random_number_generator,
        )
        X_identity_unscaled = X_unfiltered_unscaled[:, [i for i, name in enumerate(atlas_channels_for_training) if name in id_in_atlas]]

        row_sums_all = X_identity_unscaled.sum(axis=1)
        valid_mask = row_sums_all > 1e-8
        n_zero_sum = int((~valid_mask).sum())
        if n_zero_sum:
            logger.info('  Removed %d cells with zero identity-channel sum', n_zero_sum)
        X_identity_raw = X_identity_unscaled[valid_mask]
        X_identity = X_identity_raw / row_sums_all[valid_mask, np_newaxis]
        X_unscaled = X_unfiltered_unscaled[valid_mask]
        sums = row_sums_all[valid_mask]
        logger.info(
            '  Normalized: %s cells retained  (%.2f%% of loaded)',
            f'{X_identity.shape[0]:,}',
            100.0 * X_identity.shape[0] / X_unfiltered_unscaled.shape[0],
        )

        model_counter = 0

        def _is_functional_column(index_channel: tuple[int, tuple[str, str]]) -> bool:
            _, (atlas_channel, _) = index_channel
            return atlas_channel in fn_in_atlas

        targets = tuple(filter(_is_functional_column, enumerate(zip(atlas_channels_for_training, smprofiler_channels))))
        ordinary_concordances = 0
        std_concordances = 0
        for counter, (column_index, (atlas_channel, smprofiler_channel)) in enumerate(targets, 1):
            model_counter += 1
            subsection(
                f'Model [{model_counter + number_trained}/{total_models}]  '
                f'study="{study_name}"  target="{atlas_channel}"  '
                f'({counter}/{len(targets)} in study)'
            )
            ordinary, std = _train_model_one_marker(
                column_index,
                smprofiler_channel,
                final_channel_names,
                X_unscaled,
                X_identity_raw,
                sums,
                X_identity,
                self.options,
                scenario,
                summary_rows,
                model_records,
            )
            ordinary_concordances += 1 if ordinary else 0
            std_concordances += 1 if std else 0
        return model_counter, ordinary_concordances, std_concordances

def _train_model_one_marker(
    column_index: int,
    smprofiler_channel: str,
    final_channel_names: list[str],
    X_unscaled: NDArray,
    X_identity_raw: NDArray,
    sums: NDArray,
    X_identity: NDArray,
    options: TrainingOptions,
    scenario: TrainingScenarioStudy,
    summary_rows: list[dict],
    model_records: list[dict],
) -> tuple[bool, bool]:
    target_channel = smprofiler_channel
    target_col = column_index
    y = X_unscaled[:, target_col] / sums

    if y.std() < 1e-6:
        logger.warning("Skipping: target '%s' has near-zero variance", target_channel)
        return False, False

    logger.info('  Features : %d identity markers, %s cells (after S>0 filter)', X_identity.shape[1], f'{X_identity.shape[0]:,}')
    logger.info('  Target   : "%s" (norm; range %.4f – %.4f, mean %.4f)', target_channel, float(y.min()), float(y.max()), float(y.mean()))

    # Split on indices so the raw (un-normalized) test rows stay available for validating
    # the exported graph, which takes raw inputs.
    train_indices, test_indices = cast(tuple[NDArray, NDArray], train_test_split(
        np_arange(len(y)), test_size=0.2, random_state=42
    ))
    X_train, X_test = X_identity[train_indices], X_identity[test_indices]
    y_train, y_test = y[train_indices], y[test_indices]
    logger.info('  Split    : %s train / %s test', f'{len(X_train):,}', f'{len(X_test):,}')
    logger.info('  Training %d model candidates with %d-fold CV …', len(build_model_candidates()), options.cv_folds)
    t_train_start = time.monotonic()
    best_name, best_model, cv_r2, cv_r2_std = train_and_select_best(
        X_train, y_train, cv_folds=options.cv_folds
    )

    y_pred_mean, y_pred_std = predict_with_std(best_model, best_name, X_test)
    test_r2 = float(r2_score(y_test, y_pred_mean))
    test_mae = float(mean_absolute_error(y_test, y_pred_mean))
    residuals = y_test - y_pred_mean
    global_std = float(residuals.std())
    std_method = STD_METHODS[best_name]
    tree_calibration = 1.0
    if best_name in TREE_METHODS:
        tree_calibration = _tree_std_calibration(residuals, y_pred_std)
        logger.info('  Tree spread calibration γ = %.4f', tree_calibration)
    double_precision = False
    onnx_input_dtype = 'float32'
    train_seconds = time.monotonic() - t_train_start
    train_elapsed = format_elapsed(train_seconds)
    logger.info(
        '  Result   : model="%s"  test_R²=%.4f  test_MAE=%.4f'
        '  std_method=%s  global_std=%.4f  [%s]',
        best_name, test_r2, test_mae, std_method, global_std, train_elapsed,
    )

    safe_target = target_channel.replace('/', '_').replace(' ', '_')
    study_out_dir = options.output_directory / scenario.study_handle
    onnx_path = study_out_dir / f'{safe_target}.onnx'
    meta_path = study_out_dir / f'{safe_target}.meta.json'

    export_to_onnx(
        best_model, best_name, X_identity.shape[1], onnx_path,
        double_precision=double_precision, tree_calibration=tree_calibration,
    )

    n_validate = min(500, len(test_indices))
    validation_indices = test_indices[:n_validate]
    ordinary, std = validate_onnx(
        onnx_path, best_model, best_name,
        X_identity_raw[validation_indices], X_unscaled[validation_indices, target_col],
        double_precision=double_precision, tree_calibration=tree_calibration,
    )

    write_metadata_to_file(
        meta_path,
        study=scenario.study_handle,
        target_channel=target_channel,
        input_channels=final_channel_names,
        model_type=best_name,
        cv_r2=cv_r2,
        cv_r2_std=cv_r2_std,
        test_r2=test_r2,
        test_mae=test_mae,
        n_train=len(X_train),
        n_test=len(X_test),
        atlas_version=ATLAS_VERSION,
        sum_normalized=True,
        std_method=std_method,
        global_std=global_std,
        onnx_input_dtype=onnx_input_dtype,
        onnx_has_std=True,
        tree_calibration=tree_calibration,
    )

    summary_rows.append({
        'study': scenario.study_handle,
        'target': target_channel,
        'model': best_name,
        'std_method': std_method,
        'cv_R²': cv_r2,
        'test_R²': test_r2,
        'test_MAE': test_mae,
        'onnx_kb': onnx_path.stat().st_size // 1024,
    })

    if options.database_config_file is not None:
        model_records.append({
            'study': scenario.study_handle,
            'target_channel': smprofiler_channel,
            'input_channels': final_channel_names,
            'architecture_type': best_name,
            'std_method': std_method,
            'onnx_input_dtype': onnx_input_dtype,
            'onnx_has_std': True,
            'atlas_version': ATLAS_VERSION,
            'cv_r2': cv_r2,
            'test_r2': test_r2,
            'test_mae': test_mae,
            'n_train': len(X_train),
            'n_test': len(X_test),
            'training_time_seconds': train_seconds,
            'onnx_bytes': onnx_path.read_bytes(),
        })
    return ordinary, std

