"""Run a trained atlas-reference model to make per-cell "atlas-relative" calls.

A model predicts the atlas-expected intensity of one functional marker for a
"normal" cell with a given identity-marker profile. A cell is *atlas-relative
positive* for that marker when its measured intensity exceeds this expectation.

Typical usage — starting from ONNX bytes (e.g. the ``/atlas-model/`` API
endpoint, or a file written by training)::

    from smprofiler.atlas.inference import load_model, atlas_relative_positive

    session = load_model(onnx_bytes)
    # identity_intensities: shape (n_cells, n_identity), columns in the order of the
    # model's `input_channels` metadata; measured_functional: shape (n_cells,).
    positive = atlas_relative_positive(session, identity_intensities, measured_functional)

Pass **raw** intensities: identity intensities are sum-normalized internally to
match how the model was trained, and the prediction is returned on the same raw
scale as the measured value. Cells whose identity intensities sum to zero have no
reference and are reported NaN / False.
"""
import numpy as np
from onnxruntime import InferenceSession, SessionOptions


def load_model(onnx_model: bytes | str) -> InferenceSession:
    """Return an onnxruntime session for a model given as ONNX bytes or a file path."""
    options = SessionOptions()
    options.log_severity_level = 3  # errors only
    return InferenceSession(onnx_model, sess_options=options)


def _input_spec(session: InferenceSession) -> tuple[str, type]:
    """The model's single input tensor name and the numpy dtype it expects."""
    spec = session.get_inputs()[0]
    dtype = np.float64 if spec.type == "tensor(double)" else np.float32
    return spec.name, dtype


def predict_expected_intensity(
    session: InferenceSession,
    identity_intensities,
) -> np.ndarray:
    """Atlas-expected functional-marker intensity for each cell.

    Args:
        session: session from :func:`load_model`.
        identity_intensities: array of shape ``(n_cells, n_identity)`` of raw
            identity-marker intensities, with columns ordered exactly as the
            model's ``input_channels`` metadata.

    Returns:
        Array of shape ``(n_cells,)``: the expected functional intensity on the
        same raw scale as the measured intensity (so it is directly comparable).
        Cells whose identity intensities sum to zero yield ``NaN``.
    """
    features = np.asarray(identity_intensities, dtype=np.float64)
    if features.ndim != 2:
        raise ValueError("identity_intensities must be 2-D: (n_cells, n_identity)")
    row_sums = features.sum(axis=1)
    valid = row_sums > 0
    normalized = np.zeros_like(features)
    normalized[valid] = features[valid] / row_sums[valid, np.newaxis]

    input_name, dtype = _input_spec(session)
    predicted_normalized = session.run(None, {input_name: normalized.astype(dtype)})[0].reshape(-1)

    expected = predicted_normalized * row_sums
    expected[~valid] = np.nan
    return expected


def atlas_relative_positive(
    session: InferenceSession,
    identity_intensities,
    measured_functional,
) -> np.ndarray:
    """Boolean per cell: is the measured intensity above the atlas expectation?

    Args:
        session: session from :func:`load_model`.
        identity_intensities: see :func:`predict_expected_intensity`.
        measured_functional: array of shape ``(n_cells,)`` — the measured raw
            intensity of the model's target (functional) channel.

    Returns:
        Boolean array of shape ``(n_cells,)``. Cells with no reference (zero
        identity sum) are ``False``.
    """
    expected = predict_expected_intensity(session, identity_intensities)
    measured = np.asarray(measured_functional, dtype=np.float64).reshape(-1)
    with np.errstate(invalid="ignore"):  # NaN expectations compare False
        return measured > expected
