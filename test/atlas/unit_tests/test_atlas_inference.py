"""Exercise the documented atlas inference entrypoints on small exported models.

Verifies the usage contract from smprofiler.atlas.inference: sum-normalization is
applied internally, predictions come back on the raw scale, zero-identity cells
are undefined, the atlas-relative call thresholds correctly, and both float32 and
float64 (Gaussian-Process-style) models are handled without the caller specifying
a dtype.
"""
import tempfile
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression

from smprofiler.atlas.artifacts import export_to_onnx
from smprofiler.atlas.inference import (
    load_model,
    predict_expected_intensity,
    atlas_relative_positive,
)


def _export_tiny_model(double_precision: bool = False) -> bytes:
    rng = np.random.default_rng(0)
    features = rng.random((100, 3))
    target = features[:, 0] * 2.0 - features[:, 1]
    model = LinearRegression().fit(features, target)
    path = Path(tempfile.mkdtemp()) / "model.onnx"
    export_to_onnx(model, features.shape[1], path, double_precision=double_precision)
    return path.read_bytes()


def test_predict_and_atlas_relative_positive():
    session = load_model(_export_tiny_model())
    identity = np.array([[2.0, 1.0, 1.0], [1.0, 1.0, 2.0], [0.0, 0.0, 0.0]])

    expected = predict_expected_intensity(session, identity)
    assert expected.shape == (3,)
    assert np.isfinite(expected[0]) and np.isfinite(expected[1])
    assert np.isnan(expected[2])  # zero identity sum -> undefined reference

    # measured just above / below the model's own expectation, plus the undefined cell
    measured = np.where(np.isnan(expected), 0.0, expected).copy()
    measured[0] += 1.0
    measured[1] -= 1.0
    positive = atlas_relative_positive(session, identity, measured)
    assert positive.tolist() == [True, False, False]


def test_inference_auto_detects_double_precision_input():
    session = load_model(_export_tiny_model(double_precision=True))
    assert session.get_inputs()[0].type == "tensor(double)"
    # caller does not pass a dtype; the helper feeds float64 automatically
    expected = predict_expected_intensity(session, np.array([[1.0, 2.0, 3.0]]))
    assert expected.shape == (1,) and np.isfinite(expected[0])


def main():
    test_predict_and_atlas_relative_positive()
    test_inference_auto_detects_double_precision_input()
    print("atlas inference entrypoints: OK")


if __name__ == "__main__":
    main()
