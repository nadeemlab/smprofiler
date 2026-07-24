# skl2onnx `BayesianRidge` `return_std` drops the `* X` term

Draft for an upstream issue against [onnx/sklearn-onnx](https://github.com/onnx/sklearn-onnx).
Reproduced with **skl2onnx 1.20.0, scikit-learn 1.8.0, onnxruntime 1.24.4**.

## Summary

Converting a `BayesianRidge` with `options={BayesianRidge: {'return_std': True}}`
produces a standard-deviation output that does not match
`BayesianRidge.predict(X, return_std=True)`. The converter omits the element-wise
`* X` in sklearn's posterior quadratic form, so it computes a *linear* form in `X`
instead of the quadratic `xᵀ Σ x`. The mean output is correct; only the std is wrong.

## What sklearn computes

`sklearn/linear_model/_bayes.py`, `BayesianRidge.predict`:

```python
sigmas_squared_data = (np.dot(X, self.sigma_) * X).sum(axis=1)   # note the `* X`
y_std = np.sqrt(sigmas_squared_data + (1.0 / self.alpha_))
```

`(np.dot(X, self.sigma_) * X).sum(axis=1)` is the quadratic form
`Σ_i Σ_j X_i (sigma_)_{ij} X_j` — the per-sample parameter-uncertainty variance.

## What skl2onnx emits

`skl2onnx/operator_converters/linear_regressor.py`,
`convert_sklearn_bayesian_ridge` (the `return_std` branch,
[lines ~154-191](https://github.com/onnx/sklearn-onnx/blob/main/skl2onnx/operator_converters/linear_regressor.py#L154-L191)):

```python
# sigmas_squared_data = (np.dot(X, self.sigma_) * X).sum(axis=1)   # <- comment is correct
sigma = ...                                                        # initializer = sigma_
container.add_node("MatMul", [input_name, sigma], sigmaed0, ...)   # X @ sigma_
# ReduceSum over axis 1  -> sigmaed
...
container.add_initializer(alphainv, proto_dtype, [1], [1 / op.alpha_])
apply_add(scope, [sigmaed, alphainv], std0, container)             # + 1/alpha_
apply_sqrt(scope, std0, operator.outputs[1].full_name, container)  # sqrt
```

The node chain is `MatMul(X, sigma_) → ReduceSum(axis=1) → Add(1/alpha_) → Sqrt`, i.e.

```
sqrt( (X @ sigma_).sum(axis=1) + 1/alpha_ )
```

There is **no element-wise `Mul` by `X` between the `MatMul` and the `ReduceSum`**,
so the `* X` from the comment is never applied. (The `if hasattr(op, "normalize")
and op.normalize:` centering branch just above is unrelated — `normalize` was removed
from sklearn in 1.2, so that branch is dead for current models and is not the cause.)

## Impact / why it matters in practice

The `1/alpha_` noise term is shared by both formulas and usually dominates the std,
so the error's size depends on how large the (mis-computed) parameter-uncertainty
term is relative to it:

- Features on a `StandardScaler` scale (`|X| ~ 1`): the term is small vs `1/alpha_`,
  so the std is only ~1–2% off — easy to miss.
- Raw, large-magnitude features: the dropped `* X` makes the term *linear* in `X`,
  which blows up. In the repro below the std is ~90% off.

## Minimal reproduction

`test/atlas/repro_skl2onnx_br_std.py` (self-contained). Core:

```python
import numpy as np
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType
from sklearn.linear_model import BayesianRidge
from onnxruntime import InferenceSession

rng = np.random.default_rng(0)
X = rng.random((200, 3)) + np.array([50., -30., 100.])
y = X @ np.array([0.3, -0.2, 0.05]) + rng.normal(0, 0.1, len(X))
est = BayesianRidge().fit(X, y)
Xq = rng.random((25, 3)) + np.array([50., -30., 100.])

sklearn_std = est.predict(Xq, return_std=True)[1]
m = convert_sklearn(est, initial_types=[("X", DoubleTensorType([None, 3]))],
                    options={BayesianRidge: {"return_std": True}})
onnx_std = InferenceSession(m.SerializeToString()).run(None, {"X": Xq})[1].reshape(-1)

S, inv_alpha = est.sigma_, 1.0 / est.alpha_
assert np.allclose(sklearn_std, np.sqrt(((Xq @ S) * Xq).sum(1) + inv_alpha))  # with `* X`
assert np.allclose(onnx_std,    np.sqrt(( Xq @ S      ).sum(1) + inv_alpha))  # without `* X`
# max relative diff onnx vs sklearn ≈ 0.90
```

## Proposed fix

Insert an element-wise `Mul` by the (same, possibly centered) input between the
`MatMul` and the `ReduceSum`, matching the commented formula:

```
sigmaed0 = MatMul(input_name, sigma)        # X @ sigma_
prod     = Mul(sigmaed0, input_name)        # (X @ sigma_) * X      <-- add this
sigmaed  = ReduceSum(prod, axis=1)
std0     = Add(sigmaed, 1/alpha_)
y_std    = Sqrt(std0)
```

A regression test asserting `np.allclose(onnx_std, est.predict(X, return_std=True)[1])`
on large-magnitude features would catch it (the existing tests appear to use
near-unit-scale inputs, where the ~1–2% error slips under tolerance).

## Our workaround

We do not use skl2onnx's `return_std` for `BayesianRidge`. We convert mean-only and
append the exact formula (`MatMul → Mul → ReduceSum → Add → Sqrt`, with the
`StandardScaler`/centering folded into one affine on the graph input) as ONNX nodes —
see `smprofiler/atlas/artifacts.py::_append_bayesian_ridge_std`. This reproduces
sklearn to float precision (guarded by `test_bayesian_ridge_onnx_std_matches_sklearn`).
skl2onnx's Gaussian Process `return_std` is unaffected and is used directly.
