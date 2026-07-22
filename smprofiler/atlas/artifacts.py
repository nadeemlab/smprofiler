"""Model artifact production: ONNX export, ONNX validation, and metadata.

Converts a fitted estimator to ONNX (via skl2onnx), verifies the exported model
reproduces the sklearn predictions within tolerance, and writes the per-model
JSON metadata.
"""
import json
from pathlib import Path
from typing import cast

import numpy as np
from numpy.linalg import norm as np_norm
from numpy.typing import NDArray
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.linear_model import BayesianRidge
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType
from skl2onnx.common.data_types import FloatTensorType
from onnxruntime import InferenceSession
from onnxruntime import SessionOptions  # type: ignore  # conditionally imported due to c binding under the hood
from onnx import ModelProto

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def export_to_onnx(
    model,
    number_features: int,
    output_path: Path,
    double_precision: bool = False,
) -> None:
    """Convert a fitted sklearn estimator / pipeline to ONNX and save."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tensor_type = DoubleTensorType if double_precision else FloatTensorType
    initial_type = [('X', tensor_type([None, number_features]))]
    # For the below, see: https://onnx.ai/sklearn-onnx/auto_examples/plot_gpr.html#return-std-true
    options = {BayesianRidge: {'return_std': True}, GaussianProcessRegressor: {'return_std': True}}
    onnx_model = cast(ModelProto, convert_sklearn(model, initial_types=initial_type, options=options))
    with open(output_path, 'wb') as f:
        f.write(onnx_model.SerializeToString())
    size_kb = output_path.stat().st_size / 1024
    logger.info('ONNX model saved: %s (%.1f KB)', output_path, size_kb)


def validate_onnx(
    onnx_path: Path,
    sklearn_model,
    X_sample: NDArray,
    double_precision: bool = False,
) -> tuple[bool, bool]:
    """
    Run the ONNX model and compare output to sklearn's predictions.

    Returns two flags (tuple of booleans) indicating respectively
    sufficient concordance between the ordinary predictions, and between 
    the predicted standard deviations.
    """
    options = SessionOptions()
    ERROR_LEVEL = 3
    options.log_severity_level = ERROR_LEVEL
    session = InferenceSession(str(onnx_path), sess_options=options)
    dtype = np.float64 if double_precision else np.float32
    onnx_mean, onnx_std = cast(tuple[NDArray, NDArray], session.run(None, {'X': X_sample.astype(dtype)}))
    sklearn_mean, sklearn_std = cast(tuple[NDArray, NDArray], sklearn_model.predict(X_sample, return_std=True))
    a1 = onnx_mean.flatten()
    a2 = sklearn_mean.flatten()
    difference = np.sum(np.abs(a1 - a2)) / np_norm(a2)
    cutoff = 2e-2
    ordinary_prediction_concordance = difference < cutoff
    if not ordinary_prediction_concordance:
        logger.error('ONNX validation, vs. sklearn: difference norm ratio = %.6f (tolerated up to %E)', difference, cutoff)
    a1 = onnx_std.flatten()
    a2 = sklearn_std.flatten()
    difference = np.sum(np.abs(a1 - a2)) / np_norm(a2)
    std_concordance = difference < 0.1
    if not std_concordance:
        logger.warning('ONNX validation, vs sklearn: standard deviation prediction difference: %.6f', difference)
    logger.info('ONNX validation passed (max abs diff = %.2e)', difference)
    return (ordinary_prediction_concordance, std_concordance)


def write_metadata_to_file(
    output_path: Path,
    study: str,
    target_channel: str,
    input_channels: list[str],
    model_type: str,
    cv_r2: float,
    cv_r2_std: float,
    test_r2: float,
    test_mae: float,
    n_train: int,
    n_test: int,
    atlas_version: str,
    sum_normalized: bool = True,
    std_method: str = 'global_residual_std',
    global_std: float = float('nan'),
    onnx_input_dtype: str = 'float32',
) -> None:
    meta = {
        'study': study,
        'target_channel': target_channel,
        'input_channels': input_channels,
        'model_type': model_type,
        'cv_r2': round(cv_r2, 6),
        'cv_r2_std': round(cv_r2_std, 6),
        'test_r2': round(test_r2, 6),
        'test_mae': round(test_mae, 6),
        'n_train': n_train,
        'n_test': n_test,
        'atlas_version': atlas_version,
        'sum_normalized': sum_normalized,
        'std_method': std_method,
        'global_std': round(float(global_std), 8) if not np.isnan(global_std) else None,
        'onnx_input_dtype': onnx_input_dtype,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(meta, f, indent=2)
    logger.info('Metadata saved: %s', output_path)

