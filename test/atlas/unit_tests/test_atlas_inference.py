"""Exercise the documented atlas inference entrypoints on small exported models.

Verifies the usage contract from smprofiler.atlas.inference against models that
carry a std output (as production models now do): sum-normalization is applied
internally, the expected intensity comes back on the raw scale, zero-identity
cells are undefined, the z-score is finite where a reference exists, the
atlas-relative call thresholds on the z-score, both float32 and float64
(Gaussian-Process-style) models are handled without the caller specifying a
dtype, and a model exported without a std output is rejected by the z-score path.

It also guards the *numeric* sklearn↔ONNX concordance of the std output — the
check that otherwise only runs inside ``validate_onnx`` during a training run.
The BayesianRidge case is the important one: skl2onnx's own ``return_std``
converter drops the element-wise ``* X`` from sklearn's ``(X @ sigma_ * X).sum(1)``
— it emits ``MatMul(X, sigma_) → ReduceSum`` and so computes ``(X @ sigma_).sum(1)``
instead (its own inline comment states the correct formula). That is a structural
error, present in float64 too, so we append the exact formula as ONNX nodes. These
tests fail if the code ever regresses to skl2onnx's converter. See
``test/atlas/repro_skl2onnx_br_std.py`` and ``docs/skl2onnx_bayesian_ridge_std_bug.md``.
"""
import tempfile
from pathlib import Path

import numpy as np
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.linear_model import BayesianRidge, LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from smprofiler.atlas.artifacts import export_to_onnx
from smprofiler.atlas.models import predict_with_std
from smprofiler.atlas.inference import (
    load_model,
    predict_expected_intensity,
    predict_z_score,
    atlas_relative_positive,
)


def _export(model, n_features, *, double_precision=False, return_std=True,
            target_offset=0.0, tree_calibration=1.0):
    path = Path(tempfile.mkdtemp()) / "model.onnx"
    export_to_onnx(model, n_features, path, double_precision=double_precision,
                   return_std=return_std, target_offset=target_offset,
                   tree_calibration=tree_calibration)
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


def test_bayesian_ridge_onnx_std_matches_sklearn():
    """The appended exact-formula std reproduces sklearn's BayesianRidge std.

    Compares the ONNX second output against sklearn's own ``predict(return_std=True)``
    (via :func:`predict_with_std`) to float precision. A regression to skl2onnx's
    ``return_std`` converter — which drops the element-wise ``* X`` from the
    posterior quadratic form — would push this past the tolerance and fail.
    """
    model = _bayesian_ridge_model()
    session = load_model(_export(model, 3))
    # Concordance is a property of the exported graph, so feed the graph directly
    # (bypassing inference's sum-normalization) and compare on the same inputs.
    X = np.random.default_rng(7).random((40, 3))
    onnx_std = np.asarray(session.run(None, {"X": X.astype(np.float32)})[1]).reshape(-1)
    _, sklearn_std = predict_with_std(model, "bayesian_ridge", X)
    max_diff = float(np.abs(onnx_std - sklearn_std).max())
    assert np.allclose(onnx_std, sklearn_std, rtol=1e-4, atol=1e-6), max_diff


def test_gaussian_process_onnx_std_matches_sklearn():
    """The GP std (skl2onnx's native, exact-in-float64 converter) matches sklearn."""
    model, offset = _gaussian_process_model()
    session = load_model(_export(model, 3, double_precision=True, target_offset=offset))
    X = np.random.default_rng(8).random((30, 3))
    onnx_std = np.asarray(session.run(None, {"X": X.astype(np.float64)})[1]).reshape(-1)
    _, sklearn_std = predict_with_std(model, "gaussian_process", X)
    max_diff = float(np.abs(onnx_std - sklearn_std).max())
    assert np.allclose(onnx_std, sklearn_std, rtol=1e-5, atol=1e-6), max_diff


def _forest_model(estimator_cls, name, n_features=3):
    rng = np.random.default_rng(3)
    features = rng.random((150, n_features))
    target = np.sin(features[:, 0] * 3) + features[:, 1] ** 2 - features[:, 2] + rng.normal(0, 0.05, 150)
    model = Pipeline([("scaler", StandardScaler()),
                      (name, estimator_cls(n_estimators=40, random_state=1))])
    return model.fit(features, target)


def test_random_forest_onnx_std_matches_sklearn():
    """RF std = γ · across-tree spread, appended as ONNX nodes via the per-tree trick.

    skl2onnx emits mean only; we re-emit one target per tree to recover the per-tree
    predictions and compute their calibrated spread. Mean must still equal RF.predict,
    and the std must match predict_with_std at the same γ.
    """
    model = _forest_model(RandomForestRegressor, "random_forest")
    gamma = 1.7
    session = load_model(_export(model, 3, tree_calibration=gamma))
    assert len(session.get_outputs()) == 2  # mean + std
    X = np.random.default_rng(9).random((25, 3))
    outs = session.run(None, {"X": X.astype(np.float32)})
    onnx_mean, onnx_std = outs[0].reshape(-1), np.asarray(outs[1]).reshape(-1)
    exp_mean, exp_std = predict_with_std(model, "random_forest", X, calibration=gamma)
    assert np.allclose(onnx_mean, exp_mean, atol=1e-5), float(np.abs(onnx_mean - exp_mean).max())
    assert np.allclose(onnx_std, exp_std, rtol=1e-4, atol=1e-6), float(np.abs(onnx_std - exp_std).max())


def test_extra_trees_onnx_std_matches_sklearn():
    """ExtraTrees uses the same per-tree export path; std matches predict_with_std."""
    model = _forest_model(ExtraTreesRegressor, "extra_trees")
    session = load_model(_export(model, 3, tree_calibration=2.0))
    X = np.random.default_rng(10).random((20, 3))
    onnx_std = np.asarray(session.run(None, {"X": X.astype(np.float32)})[1]).reshape(-1)
    _, exp_std = predict_with_std(model, "extra_trees", X, calibration=2.0)
    assert np.allclose(onnx_std, exp_std, rtol=1e-4, atol=1e-6), float(np.abs(onnx_std - exp_std).max())


def _demonstrate_skl2onnx_blackbox_defect():
    """Diagnostic (not a CI assertion): show skl2onnx's own BayesianRidge return_std
    diverging from sklearn.

    Documents why the exact appended subgraph exists. skl2onnx drops the element-wise
    ``* X`` from ``(X @ sigma_ * X).sum(1)``; the error is structural (float64 here,
    not a rounding effect) and blows up on large-magnitude features where the
    mis-computed term dominates. Underscore-prefixed so pytest does not collect it
    (an upstream fix must not red the build); ``main()`` prints it for humans.
    """
    rng = np.random.default_rng(11)
    X = rng.random((60, 3)) + np.array([50.0, -30.0, 100.0])  # large magnitude -> dropped `* X` dominates
    y = X @ np.array([0.3, -0.2, 0.05]) + rng.normal(0, 0.1, 60)
    est = BayesianRidge().fit(X, y)
    onnx_model = convert_sklearn(
        est, initial_types=[("X", DoubleTensorType([None, 3]))],
        options={BayesianRidge: {"return_std": True}},
    )
    session = load_model(onnx_model.SerializeToString())
    blackbox_std = np.asarray(session.run(None, {"X": X.astype(np.float64)})[1]).reshape(-1)
    _, sklearn_std = est.predict(X, return_std=True)
    rel = np.abs(blackbox_std - sklearn_std) / np.abs(sklearn_std)
    print(f"  [diagnostic] skl2onnx black-box BayesianRidge std vs sklearn: "
          f"max rel diff = {rel.max():.3f} (exact appended subgraph: ~0)")


def main():
    test_predict_z_score_and_atlas_relative_positive()
    test_inference_auto_detects_double_precision_input()
    test_z_score_requires_std_output()
    test_bayesian_ridge_onnx_std_matches_sklearn()
    test_gaussian_process_onnx_std_matches_sklearn()
    test_random_forest_onnx_std_matches_sklearn()
    test_extra_trees_onnx_std_matches_sklearn()
    _demonstrate_skl2onnx_blackbox_defect()
    print("atlas inference entrypoints: OK")


if __name__ == "__main__":
    main()
