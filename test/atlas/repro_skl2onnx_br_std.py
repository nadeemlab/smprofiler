#!/usr/bin/env python
"""Minimal repro: skl2onnx's BayesianRidge ``return_std`` drops the ``* X`` term.

Run:  python test/atlas/repro_skl2onnx_br_std.py

sklearn's ``BayesianRidge.predict(return_std=True)`` computes the posterior
predictive std as a quadratic form in the input::

    sigmas_squared_data = (np.dot(X, self.sigma_) * X).sum(axis=1)   # note the `* X`
    y_std = np.sqrt(sigmas_squared_data + 1.0 / self.alpha_)

skl2onnx (``operator_converters/linear_regressor.py``,
``convert_sklearn_bayesian_ridge``) emits only ``MatMul(X, sigma_) → ReduceSum(axis=1)
→ Add(1/alpha_) → Sqrt``. The element-wise ``* X`` (the Hadamard product that turns
the linear form ``X @ sigma_`` into the quadratic form ``xᵀ Σ x``) is **missing** —
even though the converter's own inline comment reads
``# sigmas_squared_data = (np.dot(X, self.sigma_) * X).sum(axis=1)``. So skl2onnx
computes ``sqrt((X @ sigma_).sum(1) + 1/alpha_)`` instead.

The error is structural (it reproduces in float64 — it is not a precision effect).
Its size depends on how large the mis-computed parameter-uncertainty term is
relative to the shared ``1/alpha_`` noise term:
  - behind a StandardScaler (|X| ~ 1, the term is small vs 1/alpha_): ~1-2% off;
  - on raw, large-magnitude features: the dropped ``* X`` blows the term up (it is
    then linear rather than quadratic in X) and the std is wrong by ~90%.

This script confirms, on the same fitted model, that skl2onnx's output equals the
``* X``-less formula while sklearn's equals the correct one.
"""
import numpy as np
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType
from sklearn.linear_model import BayesianRidge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from onnxruntime import InferenceSession, SessionOptions


def _skl2onnx_std(estimator, X: np.ndarray) -> np.ndarray:
    opts = SessionOptions()
    opts.log_severity_level = 3
    onnx_model = convert_sklearn(
        estimator,
        initial_types=[("X", DoubleTensorType([None, X.shape[1]]))],
        options={BayesianRidge: {"return_std": True}},
    )
    session = InferenceSession(onnx_model.SerializeToString(), sess_options=opts)
    return np.asarray(session.run(None, {"X": X.astype(np.float64)})[1]).reshape(-1)


def _rel(a: np.ndarray, b: np.ndarray) -> float:
    return float((np.abs(a - b) / np.abs(b)).max())


def main() -> None:
    rng = np.random.default_rng(0)

    # (1) Bare BayesianRidge, large-magnitude features (float64 isolates the bug
    #     from any float32 rounding).
    X = rng.random((200, 3)) + np.array([50.0, -30.0, 100.0])
    y = X @ np.array([0.3, -0.2, 0.05]) + rng.normal(0, 0.1, len(X))
    est = BayesianRidge().fit(X, y)
    Xq = rng.random((25, 3)) + np.array([50.0, -30.0, 100.0])

    sklearn_std = est.predict(Xq, return_std=True)[1]
    onnx_std = _skl2onnx_std(est, Xq)
    S, inv_alpha = est.sigma_, 1.0 / est.alpha_
    with_x = np.sqrt(((Xq @ S) * Xq).sum(axis=1) + inv_alpha)   # sklearn's formula
    without_x = np.sqrt((Xq @ S).sum(axis=1) + inv_alpha)       # skl2onnx's actual formula

    print("Bare BayesianRidge, large-magnitude features (float64):")
    print(f"  skl2onnx return_std vs sklearn:        max rel diff = {_rel(onnx_std, sklearn_std):.3f}")
    print(f"  '(X@sigma * X).sum + 1/alpha' == sklearn : {np.allclose(with_x, sklearn_std)}")
    print(f"  '(X@sigma).sum   + 1/alpha' == skl2onnx  : {np.allclose(without_x, onnx_std)}"
          f"   <- the `* X` is dropped")

    # (2) StandardScaler pipeline: |X| ~ 1, so the mis-computed term is small versus
    #     the 1/alpha_ noise term and the error shrinks to ~1-2%.
    pipe = Pipeline([("scaler", StandardScaler()), ("bayesian_ridge", BayesianRidge())]).fit(X, y)
    inner = pipe.named_steps["bayesian_ridge"]
    Xq_scaled = pipe.named_steps["scaler"].transform(Xq)
    sklearn_std_p = inner.predict(Xq_scaled, return_std=True)[1]
    onnx_std_p = _skl2onnx_std(inner, Xq_scaled)
    print("\nStandardScaler -> BayesianRidge (|X| ~ 1):")
    print(f"  skl2onnx return_std vs sklearn:        max rel diff = {_rel(onnx_std_p, sklearn_std_p):.4f}")

    print("\nRoot cause: convert_sklearn_bayesian_ridge emits MatMul(X, sigma_) then "
          "ReduceSum, omitting the element-wise `* X` before the sum.")


if __name__ == "__main__":
    main()
