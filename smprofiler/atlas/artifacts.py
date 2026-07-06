"""Model artifact production: ONNX export, ONNX validation, and metadata.

Converts a fitted estimator to ONNX (via skl2onnx), verifies the exported model
reproduces the sklearn predictions within tolerance, and writes the per-model
JSON metadata sidecar.

Gaussian Process predictions involve kernel-matrix inversion and only reproduce
in double precision (float32 is off by a few percent), so GP models are exported
and run with float64 inputs; the others use float32. Callers pass
``double_precision`` and record the choice in the metadata (``onnx_input_dtype``)
so inference feeds the matching dtype.
"""
import json
from pathlib import Path

import numpy as np
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType, FloatTensorType
from onnxruntime import InferenceSession, SessionOptions

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def export_to_onnx(
    model,
    n_features: int,
    output_path: Path,
    double_precision: bool = False,
) -> None:
    """Convert a fitted sklearn estimator / pipeline to ONNX and save."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tensor_type = DoubleTensorType if double_precision else FloatTensorType
    initial_type = [("X", tensor_type([None, n_features]))]
    onnx_model = convert_sklearn(model, initial_types=initial_type)
    with open(output_path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    size_kb = output_path.stat().st_size / 1024
    logger.info("ONNX model saved: %s (%.1f KB)", output_path, size_kb)


def validate_onnx(
    onnx_path: Path,
    sklearn_model,
    X_sample: np.ndarray,
    double_precision: bool = False,
) -> bool:
    """
    Run the ONNX model and compare output to sklearn's predictions.
    Returns True if outputs match within tolerance.
    """
    ort_opts = SessionOptions()
    ort_opts.log_severity_level = 3  # 0=VERBOSE … 3=ERROR (onnxruntime's own C-level control)
    sess = InferenceSession(str(onnx_path), sess_options=ort_opts)
    dtype = np.float64 if double_precision else np.float32
    onnx_pred = sess.run(None, {"X": X_sample.astype(dtype)})[0].flatten()
    sklearn_pred = sklearn_model.predict(X_sample)
    max_diff = np.abs(onnx_pred - sklearn_pred).max()
    if max_diff > 1e-3:
        logger.warning("ONNX validation: max abs diff = %.6f (tolerated up to 1e-3)", max_diff)
        return False
    logger.info("ONNX validation passed (max abs diff = %.2e)", max_diff)
    return True


def write_metadata(
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
    std_method: str = "global_residual_std",
    global_std: float = float("nan"),
    onnx_input_dtype: str = "float32",
) -> None:
    meta = {
        "study": study,
        "target_channel": target_channel,
        "input_channels": input_channels,
        "model_type": model_type,
        "cv_r2": round(cv_r2, 6),
        "cv_r2_std": round(cv_r2_std, 6),
        "test_r2": round(test_r2, 6),
        "test_mae": round(test_mae, 6),
        "n_train": n_train,
        "n_test": n_test,
        "atlas_version": atlas_version,
        "sum_normalized": sum_normalized,
        "std_method": std_method,
        "global_std": round(float(global_std), 8) if not np.isnan(global_std) else None,
        "onnx_input_dtype": onnx_input_dtype,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Metadata saved: %s", output_path)
