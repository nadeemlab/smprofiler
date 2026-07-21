"""Exercise the documented atlas inference entrypoints on small exported models.

Verifies the usage contract from smprofiler.atlas.inference against models that
carry a std output (as production models now do): sum-normalization is applied
internally, the expected intensity comes back on the raw scale, zero-identity
cells are undefined, the z-score is finite where a reference exists, the
atlas-relative call thresholds on the z-score, both float32 and float64
(Gaussian-Process-style) models are handled without the caller specifying a
dtype, and a model exported without a std output is rejected by the z-score path.
"""
import tempfile
from pathlib import Path

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.linear_model import BayesianRidge, LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from smprofiler.atlas.artifacts import export_to_onnx
from smprofiler.atlas.inference import (
    load_model,
    predict_expected_intensity,
    predict_z_score,
    atlas_relative_positive,
)


def _export(model, n_features, *, double_precision=False, return_std=True, target_offset=0.0):
    path = Path(tempfile.mkdtemp()) / "model.onnx"
    export_to_onnx(model, n_features, path, double_precision=double_precision,
                   return_std=return_std, target_offset=target_offset)
    return path.read_bytes()


def _bayesian_ridge_model(n_features=3):
    rng = np.random.default_rng(0)
    features = rng.random((200, n_features))
    target = features[:, 0] * 2.0 - features[:, 1] + rng.normal(0, 0.05, 200)
    model = Pipeline([("scaler", StandardScaler()), ("bayesian_ridge", BayesianRidge())])
    return model.fit(features, target)


def _gaussian_process_model(n_features=3):
    """A GP fitted on mean-centered targets, mirroring the training pipeline."""
    rng = np.random.default_rng(1)
    features = rng.random((120, n_features))
    target = features[:, 0] * 0.5 - features[:, 1] * 0.3 + 0.4 + rng.normal(0, 0.02, 120)
    offset = float(target.mean())
    kernel = ConstantKernel(1.0) * RBF(1.0) + WhiteKernel(0.01)
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("gaussian_process", GaussianProcessRegressor(kernel=kernel, normalize_y=False,
                                                      random_state=42)),
    ])
    model.fit(features, target - offset)
    return model, offset


def test_predict_z_score_and_atlas_relative_positive():
    session = load_model(_export(_bayesian_ridge_model(), 3))
    assert len(session.get_outputs()) == 2  # mean + std
    identity = np.array([[2.0, 1.0, 1.0], [1.0, 1.0, 2.0], [0.0, 0.0, 0.0]])

    expected = predict_expected_intensity(session, identity)
    assert expected.shape == (3,)
    assert np.isfinite(expected[0]) and np.isfinite(expected[1])
    assert np.isnan(expected[2])  # zero identity sum -> undefined reference

    # measured just above / below the model's own expectation, plus the undefined cell
    measured = np.where(np.isnan(expected), 0.0, expected).copy()
    measured[0] += 1.0
    measured[1] -= 1.0

    z = predict_z_score(session, identity, measured)
    assert z.shape == (3,)
    assert z[0] > 0 and z[1] < 0  # above / below expectation
    assert np.isnan(z[2])         # no reference

    # threshold=0 reproduces the plain above-expectation call
    positive = atlas_relative_positive(session, identity, measured)
    assert positive.tolist() == [True, False, False]
    # a high threshold requires exceeding expectation by many std -> the +1.0 cell drops out
    strict = atlas_relative_positive(session, identity, measured, threshold=1e6)
    assert strict.tolist() == [False, False, False]


def test_inference_auto_detects_double_precision_input():
    model, offset = _gaussian_process_model()
    session = load_model(_export(model, 3, double_precision=True, target_offset=offset))
    assert session.get_inputs()[0].type == "tensor(double)"
    # caller does not pass a dtype; the helper feeds float64 automatically
    identity = np.array([[1.0, 2.0, 3.0]])
    expected = predict_expected_intensity(session, identity)
    assert expected.shape == (1,) and np.isfinite(expected[0])
    z = predict_z_score(session, identity, np.array([5.0]))
    assert z.shape == (1,) and np.isfinite(z[0])


def test_z_score_requires_std_output():
    """A model exported without return_std has one output; the z-score path must reject it."""
    features = np.random.default_rng(2).random((50, 3))
    model = LinearRegression().fit(features, features[:, 0])
    session = load_model(_export(model, 3, return_std=False))
    assert len(session.get_outputs()) == 1
    # the mean-only entrypoint still works
    assert predict_expected_intensity(session, np.array([[1.0, 2.0, 3.0]])).shape == (1,)
    try:
        predict_z_score(session, np.array([[1.0, 2.0, 3.0]]), np.array([1.0]))
    except ValueError:
        pass
    else:
        raise AssertionError("predict_z_score should reject a model with no std output")


def main():
    test_predict_z_score_and_atlas_relative_positive()
    test_inference_auto_detects_double_precision_input()
    test_z_score_requires_std_output()
    print("atlas inference entrypoints: OK")


if __name__ == "__main__":
    main()
