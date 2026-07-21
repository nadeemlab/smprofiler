"""Run a trained atlas-reference model to make per-cell "atlas-relative" calls.

A model predicts, for a "normal" cell with a given identity-marker profile, both
the atlas-expected intensity of one functional marker **and** the predictive
standard deviation of that expectation. The primary output is the per-cell
**z-score** — how many predictive standard deviations the measured intensity sits
above the atlas expectation. A cell is *atlas-relative positive* for the marker
when its z-score exceeds a threshold (``0`` = simply above expectation; ``2`` = a
~2-sigma, uncertainty-calibrated call).

Both the mean and the std come from the ONNX model itself: models are exported
with ``return_std=True`` so the graph has two outputs (mean at index 0, per-sample
std at index 1). There is no separate Python/pickle uncertainty path.

Typical usage — starting from ONNX bytes (e.g. the ``/atlas-model/`` API
endpoint, or a file written by training)::

    from smprofiler.atlas.inference import load_model, atlas_relative_positive

    session = load_model(onnx_bytes)
    # identity_intensities: shape (n_cells, n_identity), columns in the order of the
    # model's `input_channels` metadata; measured_functional: shape (n_cells,).
    z = predict_z_score(session, identity_intensities, measured_functional)
    positive = atlas_relative_positive(session, identity_intensities, measured_functional)

Pass **raw** intensities: identity intensities are sum-normalized internally to
match how the model was trained, and the expected intensity is returned on the
same raw scale as the measured value. Cells whose identity intensities sum to zero
have no reference and are reported NaN / False.
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


def _run(session: InferenceSession, identity_intensities):
    """Sum-normalize identity intensities and run the model.

    Returns ``(outputs, row_sums, valid)`` where ``outputs`` is the raw list of
    ONNX outputs (mean at index 0, std at index 1 when present), ``row_sums`` is
    the per-cell identity-channel sum, and ``valid`` marks cells with a nonzero
    sum (a defined atlas reference).
    """
    features = np.asarray(identity_intensities, dtype=np.float64)
    if features.ndim != 2:
        raise ValueError("identity_intensities must be 2-D: (n_cells, n_identity)")
    row_sums = features.sum(axis=1)
    valid = row_sums > 0
    normalized = np.zeros_like(features)
    normalized[valid] = features[valid] / row_sums[valid, np.newaxis]

    input_name, dtype = _input_spec(session)
    outputs = session.run(None, {input_name: normalized.astype(dtype)})
    return outputs, row_sums, valid


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
    outputs, row_sums, valid = _run(session, identity_intensities)
    predicted_normalized = outputs[0].reshape(-1)
    expected = predicted_normalized * row_sums
    expected[~valid] = np.nan
    return expected


def predict_z_score(
    session: InferenceSession,
    identity_intensities,
    measured_functional,
) -> np.ndarray:
    """Per-cell z-score of the measured intensity against the atlas expectation.

    ``z = (measured - expected_mean) / expected_std`` — how many predictive
    standard deviations the measured intensity sits above what the atlas expects
    for a normal cell with this identity profile. The mean and std are read from
    the model's two ONNX outputs; scale cancels, so the z-score is the same on the
    normalized and raw intensity scales.

    Args:
        session: session from :func:`load_model`.
        identity_intensities: see :func:`predict_expected_intensity`.
        measured_functional: array of shape ``(n_cells,)`` — the measured raw
            intensity of the model's target (functional) channel.

    Returns:
        Array of shape ``(n_cells,)`` of z-scores. Cells with no reference (zero
        identity sum) are ``NaN``.

    Raises:
        ValueError: if the model has no std output (exported without
            ``return_std``); re-export it so z-scores can be computed.
    """
    outputs, row_sums, valid = _run(session, identity_intensities)
    if len(outputs) < 2:
        raise ValueError(
            "Model has no std output; z-scores need a model exported with "
            "return_std=True (two ONNX outputs: mean, std)."
        )
    predicted_normalized = outputs[0].reshape(-1)
    std_normalized = np.asarray(outputs[1]).reshape(-1)
    measured = np.asarray(measured_functional, dtype=np.float64).reshape(-1)

    z = np.full(row_sums.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        measured_normalized = np.zeros_like(row_sums)
        measured_normalized[valid] = measured[valid] / row_sums[valid]
        z[valid] = (measured_normalized[valid] - predicted_normalized[valid]) / std_normalized[valid]
    return z


def atlas_relative_positive(
    session: InferenceSession,
    identity_intensities,
    measured_functional,
    threshold: float = 0.0,
) -> np.ndarray:
    """Boolean per cell: is the measured intensity above the atlas expectation?

    Thresholds the per-cell z-score from :func:`predict_z_score`. ``threshold=0``
    (the default) marks any cell measured above the expected mean — the same call
    as a plain ``measured > expected`` comparison, now uncertainty-aware. A larger
    threshold (e.g. ``2``) requires the measurement to exceed the expectation by
    that many predictive standard deviations.

    Args:
        session: session from :func:`load_model`.
        identity_intensities: see :func:`predict_expected_intensity`.
        measured_functional: array of shape ``(n_cells,)`` — the measured raw
            intensity of the model's target (functional) channel.
        threshold: minimum z-score for a positive call.

    Returns:
        Boolean array of shape ``(n_cells,)``. Cells with no reference (zero
        identity sum) are ``False``.
    """
    z = predict_z_score(session, identity_intensities, measured_functional)
    with np.errstate(invalid="ignore"):  # NaN z-scores compare False
        return z > threshold
