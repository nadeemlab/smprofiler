# Atlas model uncertainty: current state

How atlas-reference models produce a per-cell **z-score**, and how each supported
architecture's predictive **standard deviation** reaches the exported ONNX model. This
is the current-state reference; usage is in `docs/atlas_models.md`.

## What the model outputs, and why

Atlas models are chosen around an **input-dependent predictive standard deviation**: the
candidate set is deliberately limited to architectures whose uncertainty varies with the
input. Every exported graph computes, from raw identity intensities `X` and the raw
measured functional intensity `measured`:

```
S        = rowsum(X)                     # identity sum, per cell
mean_n   = model(X / S)                  # expected target intensity, normalized scale
std_n    = predictive std at X / S
z        = (measured / S − mean_n) / std_n
mean     = mean_n · S,  std = std_n · S  # secondary outputs, raw scale
```

The **primary result is `z`**. A cell is **atlas-relative positive** when `z` exceeds a
threshold: `0` = above expectation; `2` = a roughly two-sigma call. Cells with zero
identity sum have no reference and yield `NaN` in all outputs (inside the graph the
division uses `1` instead of `0`, so the estimator always sees finite input, and the
result is masked afterwards). Uncertainty and normalization live entirely in the ONNX
file: there is no separate Python or pickle path.

## Supported architectures

| Architecture      | Std source                          | How it reaches ONNX |
| ----------------- | ----------------------------------- | ------------------- |
| `bayesian_ridge`  | Bayesian posterior std              | exact formula appended as ONNX nodes (skl2onnx's own converter is wrong, below) |
| `random_forest`   | spread across trees, calibrated     | re-emit one target per tree → per-tree spread, in-graph |
| `extra_trees`     | spread across trees, calibrated     | same |

Excluded:

- Gaussian process regression: exact posterior std, but O(N³) training cannot use a
  meaningful fraction of the ~2M-cell atlas.
- Boosting and purely-mean regressors (ridge, elastic net, huber, gradient boosting,
  XGBoost): std is either a single residual scale or, for additive boosting, has no
  meaningful across-tree spread.

`predict_with_std` raises for anything outside the supported set, keeping the invariant
enforced in code. No `StandardScaler` is used: the z-score is scale-free.

Verified stack: skl2onnx 1.20, onnxruntime 1.23, scikit-learn 1.9, onnx 1.22.

## BayesianRidge: skl2onnx's `return_std` is wrong, so the exact formula is appended

skl2onnx's built-in BayesianRidge `return_std` converter emits
`MatMul(X, sigma_) → ReduceSum` and **drops the element-wise `* X`** from sklearn's
`(X @ sigma_ * X).sum(1)`, computing a linear form instead of the quadratic `xᵀΣx`. The
shared `1/alpha_` noise term masks it: about 1–2% off behind a `StandardScaler`, but an
order of magnitude on raw features. Full analysis and a runnable repro are in
`docs/skl2onnx_bayesian_ridge_std_bug.md` and `test/atlas/repro_skl2onnx_br_std.py`.

So for BayesianRidge the mean-only graph is converted and the exact std is appended as
nodes (`_append_bayesian_ridge_std`):

```
xc  = (X_n − X_offset_) / X_scale_       # BayesianRidge input-centering, folded in
std = sqrt( sum(xc · Σ · xc, axis=1) + 1/alpha_ )
```

This reproduces sklearn to float precision.

## Tree ensembles: per-tree spread as a calibrated std

A forest has no posterior std; its natural uncertainty is the spread of its trees'
predictions. skl2onnx converts the forest to a single `TreeEnsembleRegressor` that sums
each leaf's (pre-divided) weight into one target, so it outputs only the mean. The op is
re-emitted with **one target per tree** (`target_ids = target_treeids`, weights ×
`n_trees`, `n_targets = n_trees`, `aggregate = SUM`) so it returns the `(batch, n_trees)`
per-tree predictions. Mean and spread are then both computed from that one node
(`_append_tree_ensemble_std`):

```
mean = mean_k(pred_k)
std  = γ · sqrt( mean_k(pred_k²) − mean_k(pred_k)² )
```

**Calibration `γ`.** The raw across-tree spread is epistemic only: it omits the noise
term and under-estimates the predictive std. It is scaled by a single constant
`γ = RMS(residual / spread)` fitted on the train/test holdout (`_tree_std_calibration`)
and baked into the graph, giving a roughly unit-variance z-score. `γ` fixes the average
scale, not per-region heteroscedasticity; unlike the BayesianRidge posterior std this is
a calibrated proxy, not a closed-form predictive distribution. On very small training
sets (such as the unit-test fixture) `γ` can be large because the bounded trees barely
disagree; the value is recorded in the metadata as `tree_calibration`.

**Size.** ONNX tree size grows with depth × `n_estimators`. The candidates use 100 trees
with `max_depth=8` and `min_samples_leaf=100`, which keeps a model at a few MB at most;
the export logs a warning above 5 MB. These bounds are a first guess to be revisited
after a full-data run.

## Validation

`validate_onnx` runs each exported model on **raw** holdout rows and compares all three
outputs against the numpy/sklearn reference built from `predict_with_std`
(`reference_outputs`): mean by relative L1 (tolerance 1e-3), std and z with
`allclose` (rtol 1e-2). It returns two flags (ordinary prediction, std) that the
training summary counts. The unit tests in `test/atlas/unit_tests/test_atlas_inference.py`
assert the graph contract and numeric concordance for every architecture, so a
regression to skl2onnx's converter fails the tests. `atlas` is a submodule of the
Makefile test harness (`make unit-test-atlas`).

## Where the code lives

- `smprofiler/atlas/model_selection_fitting.py`: candidates, CV selection,
  `STD_METHODS`/`TREE_METHODS`, `predict_with_std`, `_tree_std_calibration`.
- `smprofiler/atlas/artifacts.py`: `export_to_onnx`; the appended std subgraphs
  (`_append_bayesian_ridge_std`, `_append_tree_ensemble_std`); the in-graph
  normalization and z-score (`_prepend_row_sum_normalization_and_z`); `validate_onnx`,
  `reference_outputs`; `write_metadata_to_file`.
- `smprofiler/atlas/inference.py`: `predict_z_score`, `predict_expected_intensity`,
  `predict_expected_std`, `atlas_relative_positive`.
- `smprofiler/atlas/training.py`: end-to-end run (plan → train → export → validate →
  metadata), including the tree `γ` fit.
- Persistence/API: `db/accessors/atlas_models.py` (`onnx_has_std` column),
  `apiserver/app/main.py` (`X-Onnx-Has-Std` / `X-Onnx-Input-Dtype` headers).

## Future: model-agnostic std for boosting

Boosting is excluded because its additive trees have no across-tree spread. If it is
ever needed, a model-agnostic fallback is to embed a random training subsample in the
graph and, at inference, weight those points by a distance-to-query kernel to estimate a
local predictive distribution (moments computed in-graph with the same node-appending
machinery). Design only; not implemented, and not needed for the architectures above.
