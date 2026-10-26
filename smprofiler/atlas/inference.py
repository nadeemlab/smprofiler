"""Run a trained atlas-reference model to determine per-cell "atlas-relative" z-scores.

The ONNX models take raw identity-marker intensities `X` (columns in the model's
`input_channels` order) and the raw measured intensity of the target functional
marker, and return `z`, `mean` and `std` per cell (see `smprofiler.atlas.artifacts`).
Normalization happens inside the graph; nothing here rescales the inputs.
"""
import numpy as np
from numpy.typing import NDArray
from onnxruntime import InferenceSession
from onnxruntime import SessionOptions  # type: ignore  # conditionally imported due to c binding under the hood

_INPUT_NAMES = ('X', 'measured')
_OUTPUT_NAMES = ('z', 'mean', 'std')


def load_model(onnx_model: bytes | str) -> InferenceSession:
    """Return an onnxruntime session for a model given as ONNX bytes or a file path."""
    options = SessionOptions()
    ERROR_LEVEL = 3
    options.log_severity_level = ERROR_LEVEL
    return InferenceSession(onnx_model, sess_options=options)


def predict_z_score(
    session: InferenceSession,
    identity_intensities: NDArray,
    measured_functional: NDArray,
) -> NDArray:
    """
    Atlas-relative functional-marker z-score: how many predictive standard deviations
    the measured intensity sits above the atlas expectation for a cell with the given
    identity profile.

    Args:
        session: session from :func:`load_model`.
        identity_intensities: raw identity-marker intensities, shape
            ``(n_cells, n_identity)``, columns in the model's ``input_channels`` order.
        measured_functional: raw intensity of the target channel, shape ``(n_cells,)``.

    Returns:
        Array of shape ``(n_cells,)``; ``NaN`` where the identity intensities sum to zero.
    """
    return _run(session, identity_intensities, measured_functional)['z']


def predict_expected_intensity(session: InferenceSession, identity_intensities: NDArray) -> NDArray:
    """Expected raw intensity of the target channel for each cell (NaN where no reference)."""
    n_cells = np.asarray(identity_intensities).shape[0]
    return _run(session, identity_intensities, np.zeros(n_cells))['mean']


def predict_expected_std(session: InferenceSession, identity_intensities: NDArray) -> NDArray:
    """Predictive standard deviation of the target channel, raw scale, per cell."""
    n_cells = np.asarray(identity_intensities).shape[0]
    return _run(session, identity_intensities, np.zeros(n_cells))['std']


def atlas_relative_positive(
    session: InferenceSession,
    identity_intensities: NDArray,
    measured_functional: NDArray,
    threshold: float = 0.0,
) -> NDArray:
    """
    Boolean per cell: is the z-score above `threshold`? `0` means above the atlas
    expectation; `2` is a roughly two-sigma call. Cells without a reference are False.
    """
    z_score = predict_z_score(session, identity_intensities, measured_functional)
    with np.errstate(invalid='ignore'):
        return z_score > threshold


def _run(session: InferenceSession, identity_intensities: NDArray, measured_functional: NDArray) -> dict[str, NDArray]:
    input_names = [spec.name for spec in session.get_inputs()]
    output_names = [spec.name for spec in session.get_outputs()]
    if list(input_names) != list(_INPUT_NAMES) or set(_OUTPUT_NAMES) - set(output_names):
        raise ValueError(
            f'Model does not follow the atlas contract: inputs {input_names}, outputs {output_names}; '
            f'expected inputs {list(_INPUT_NAMES)} and outputs {list(_OUTPUT_NAMES)}.'
        )
    dtype = _input_dtype(session)
    X = np.asarray(identity_intensities, dtype=dtype)
    measured = np.asarray(measured_functional, dtype=dtype).reshape(-1)
    if X.ndim != 2:
        raise ValueError('identity_intensities must be 2-D: (n_cells, n_identity)')
    if measured.shape[0] != X.shape[0]:
        raise ValueError('measured_functional must have one value per cell')
    outputs = session.run(list(_OUTPUT_NAMES), {'X': X, 'measured': measured})
    return {name: np.asarray(o).reshape(-1) for name, o in zip(_OUTPUT_NAMES, outputs)}


def _input_dtype(session: InferenceSession) -> type:
    """The numpy dtype the model's `X` input expects."""
    spec = session.get_inputs()[0]
    return np.float64 if spec.type == 'tensor(double)' else np.float32
