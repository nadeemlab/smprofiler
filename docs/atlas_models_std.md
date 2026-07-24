# Atlas model uncertainty: current state

How atlas-reference models produce a per-cell **z-score**, and how each supported
architecture's predictive **standard deviation** reaches the exported ONNX model. This
is the current-state reference; usage is in `docs/atlas_models.md`.

## What the model outputs, and why

Atlas models are chosen around an **input-dependent predictive standard deviation** —
the candidate set is deliberately limited to architectures whose uncertainty varies
with the input. Every model is exported with a **second ONNX output**: a per-sample std
alongside the mean. Inference reads both, so uncertainty lives entirely in the ONNX file
— there is no separate Python/pickle path.

The **primary result is the per-cell z-score**. For a cell with identity-marker profile
`x` and measured functional intensity `measured`:

```
z = (measured − expected_mean) / expected_std
```

`expected_mean` and `expected_std` are the model's two ONNX outputs. Identity
intensities are sum-normalized internally; because the std is on the normalized target
scale and the mean is rescaled by the identity-row sum, the scale cancels — the z-score
is the same on the normalized and raw scales. A cell is **atlas-relative positive** when
`z` exceeds a threshold: `0` = simply above expectation (uncertainty-aware); `2` = a
~2-sigma call. Cells with zero identity sum have no reference and are `NaN` / `False`.

## Supported architectures

Only architectures whose predictive std genuinely depends on `x` **and** can be emitted
as an ONNX output are kept:

| Architecture      | Std source | How it reaches ONNX |
| ----------------- | ---------- | ------------------- |
| `gaussian_process`| GP posterior std | skl2onnx `return_std=True` (exact in float64) |
| `bayesian_ridge`  | Bayesian posterior std | exact formula appended as ONNX nodes (skl2onnx's own converter is wrong — below) |
| `random_forest`   | spread across trees, calibrated | re-emit one target per tree → per-tree spread, in-graph |
| `extra_trees`     | spread across trees, calibrated | same |

Boosting and purely-mean regressors (ridge, elastic net, huber, gradient boosting,
XGBoost) are **excluded**: their std is either input-independent (a single residual
scale) or, for additive boosting, has no meaningful across-tree spread.
`predict_with_std` raises for anything outside the supported set, keeping the invariant
enforced in code.

Verified stack: skl2onnx 1.20, onnxruntime 1.24, scikit-learn 1.8.

## BayesianRidge: skl2onnx's `return_std` is wrong — we append the exact formula

skl2onnx's built-in BayesianRidge `return_std` converter is **systematically wrong**: it
emits `MatMul(X, sigma_) → ReduceSum` and **drops the element-wise `* X`** from sklearn's
`(X @ sigma_ * X).sum(1)`, computing a linear form instead of the quadratic `xᵀΣx` (its
own inline comment states the correct formula). The shared `1/alpha_` noise term masks
it: ~1–2% off behind a `StandardScaler` (where `|X| ~ 1`), but an order of magnitude on
raw large-magnitude features. Full analysis and a runnable repro are in
`docs/skl2onnx_bayesian_ridge_std_bug.md` and `test/atlas/repro_skl2onnx_br_std.py`.

So for BayesianRidge we convert mean-only and append the exact std as ONNX nodes
(`_append_bayesian_ridge_std`):

```
xc  = (scaler(X) − X_offset_) / X_scale_      # BayesianRidge input-centering, folded in
std = sqrt( sum(xc · Σ · xc, axis=1) + 1/alpha_ )
```

The `StandardScaler` and centering are folded into one affine `xc = X·A − B` on the graph
input, so the subgraph is independent of skl2onnx's internal node names. This reproduces
sklearn **bit-for-bit**. skl2onnx's Gaussian Process `return_std` is unaffected and is
used directly.

## Gaussian Process: target-centering

skl2onnx's GP `return_std` converter crashes when `normalize_y=True` (it mishandles the
y-rescaling, raising `TypeError … OnnxMul`), so the GP uses `normalize_y=False`. To keep
fit quality with a zero-mean prior, the training target is **mean-centered** before
fitting and the constant offset is **baked back into the ONNX mean output** as an `Add`
node (`_bake_target_offset`); the exported model predicts on the original scale and
inference needs no offset knowledge. The std is shift-invariant and left untouched.
Centering is applied uniformly across candidates so CV selection is fair (R² and MAE are
shift-invariant, so reported metrics equal raw-scale values).

## Tree ensembles: per-tree spread as a calibrated std

A forest has no posterior std; its natural uncertainty is the spread of its trees'
predictions. skl2onnx converts the forest to a single `TreeEnsembleRegressor` that sums
each leaf's (pre-divided) weight into one target — i.e. it outputs only the mean. We
re-emit that op with **one target per tree** (`target_ids = target_treeids`, weights ×
`n_trees`, `n_targets = n_trees`, `aggregate = SUM`), so it returns the `(batch, n_trees)`
per-tree predictions. The mean and spread are then both computed from that one node
(`_append_tree_ensemble_std`):

```
mean = mean_k(pred_k)
std  = γ · sqrt( mean_k(pred_k²) − mean_k(pred_k)² )
```

Reusing the single tree node (rather than keeping skl2onnx's mean node plus a second copy
of the trees) keeps the graph **~1× the vanilla size**.

**Calibration `γ`.** The raw across-tree spread is *epistemic only* — it omits the noise
term and under-estimates the predictive std (on a holdout the z-score has variance ~1.3,
not 1). So it is scaled by a single constant `γ = RMS(residual / spread)` fitted on the
train/test holdout (`_tree_std_calibration`) and baked into the graph, giving a
~unit-variance z-score. `γ` is a **global scalar**: it fixes the average scale, not
per-region heteroscedasticity. Unlike the BayesianRidge/GP posterior std, this is a
calibrated proxy, not a closed-form predictive distribution.

**Size caveat.** ONNX tree size grows with tree depth × `n_estimators`. With unbounded
depth on large training sets the graph reaches tens of MB (e.g. ~14 MB for a 200-tree
`extra_trees` on the ~950-cell fixture) — a concern for browser (`onnxruntime-web`)
serving, and unbounded depth also overfits. Bounding `max_depth` / `min_samples_leaf` is
the lever if size or overfitting becomes a problem; the candidates currently leave them
unbounded.

## Precision

Gaussian Process predictions involve kernel-matrix inversion and only reproduce in
double precision (float32 is off by a few percent), so GP models are exported and run
with **float64** inputs; the others use **float32**. The chosen dtype is recorded in the
metadata (`onnx_input_dtype`) so inference feeds the matching type.

## Validation

`validate_onnx` runs each exported model and compares against sklearn: the mean to
`predict(X) + target_offset` (tol 1e-3), and the std to `predict_with_std` (rtol 1e-2).
A fast unit-test guard (`test/atlas/unit_tests/test_atlas_inference.py`) additionally
asserts numeric concordance for every architecture — including the BayesianRidge exact
subgraph and the tree per-tree spread — so a regression to skl2onnx's converter fails
the tests. CI note: `atlas` is not yet in the Makefile `SUBMODULES`, so these tests are
run directly (`python test/atlas/unit_tests/…`), not in the docker matrix.

## Where the code lives

- `smprofiler/atlas/models.py` — candidates (`bayesian_ridge`, `gaussian_process`,
  `random_forest`, `extra_trees`), CV selection, `STD_METHODS`/`TREE_METHODS`,
  `predict_with_std`, `_tree_std_calibration`.
- `smprofiler/atlas/artifacts.py` — `export_to_onnx`; the appended std subgraphs
  (`_append_bayesian_ridge_std`, `_append_tree_ensemble_std`); `_bake_target_offset`;
  `validate_onnx`; `write_metadata`.
- `smprofiler/atlas/inference.py` — `predict_z_score`, `predict_expected_intensity`,
  `atlas_relative_positive`.
- `smprofiler/atlas/training.py` — end-to-end run (train → export → validate → metadata),
  including the tree `γ` fit.
- Persistence/API: `db/accessors/atlas_models.py` (+ `onnx_has_std` column),
  `apiserver/app/main.py` (`X-Onnx-Has-Std` / `X-Onnx-Input-Dtype` headers).

## Future: model-agnostic std for boosting

Boosting (`GradientBoosting`, XGBoost) is excluded because its additive trees have no
across-tree spread. If it is ever needed, a model-agnostic fallback is to embed a random
training subsample in the graph and, at inference, weight those points by a
distance-to-query kernel to estimate a local predictive distribution (moments computed
in-graph with the same node-appending machinery). Design only — not implemented, and not
needed for the four architectures above.
