"""Run a trained atlas-reference model to determine per-cell "atlas-relative" z-scores.
"""
from typing import cast

import numpy as np
from numpy.typing import NDArray
from onnxruntime import InferenceSession 
from onnx import SessionOptions  # type: ignore  # because of import boundary for c API


def load_model(onnx_model: bytes | str) -> InferenceSession:
    """Return an onnxruntime session for a model given as ONNX bytes or a file path."""
    options = SessionOptions()
    ERROR_LEVEL = 3
    options.log_severity_level = ERROR_LEVEL
    return InferenceSession(onnx_model, sess_options=options)

def compute_marker_z_score(
    session: InferenceSession,
    identity_intensities: NDArray,
    measured_functional: NDArray,
) -> np.ndarray:
    """Atlas-relative functional-marker z-score.

    Args:
        session: session from :func:`load_model`.
        identity_intensities: array of shape ``(n_cells, n_identity)`` of raw
            identity-marker intensities, with columns ordered exactly as the
            model's ``input_channels`` metadata.

    Returns:
        Array of shape ``(n_cells,)``.
    """
    X_unscaled = np.asarray(identity_intensities, dtype=np.float64)
    if X_unscaled.ndim != 2:
        raise ValueError('identity_intensities must be 2-D: (n_cells, n_identity)')
    row_sums = X_unscaled.sum(axis=1)
    valid = row_sums > 0
    X = np.zeros_like(X_unscaled)
    X[valid] = X_unscaled[valid] / row_sums[valid, np.newaxis]
    y_measured = np.zeros_like(measured_functional)
    y_measured[valid] = measured_functional / row_sums[valid]
    input_name, dtype = _input_spec(session)
    # For the below, see: https://onnx.ai/sklearn-onnx/auto_examples/plot_gpr.html#return-std-true
    _y, _standard_deviation = cast(tuple[NDArray, NDArray], session.run(None, {input_name: X.astype(dtype)})[0])
    y = _y.reshape(-1)
    standard_deviation = _standard_deviation.reshape(-1)
    z_score = (y_measured - y) / standard_deviation
    z_score[~valid] = np.nan
    return z_score

def atlas_relative_positive(
    session: InferenceSession,
    identity_intensities,
    measured_functional,
) -> np.ndarray:
    """Boolean per cell: is the measured intensity above the atlas expectation?
    See ``compute_marker_z_score``.
    """
    z_score = compute_marker_z_score(session, identity_intensities, measured_functional)
    with np.errstate(invalid='ignore'):
        return z_score > 0

def _input_spec(session: InferenceSession) -> tuple[str, type]:
    """The model's single input tensor name and the numpy dtype it expects."""
    spec = session.get_inputs()[0]
    dtype = np.float64 if spec.type == 'tensor(double)' else np.float32
    return spec.name, dtype

