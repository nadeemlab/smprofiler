# Atlas model training

## What the model outputs
For our atlas-reference models, we deliberately limit ourselves to candidate architectures
whose uncertainty varies non-trivially with input. From raw identity intensities `X` and the raw
measured functional intensity `measured`, every exported graph computes:

```
S        = rowsum(X)
mean_n   = model(X / S)
std_n    = predictive std at X / S
z        = ((measured / S) − mean_n) / std_n
mean     = mean_n * S
std      = std_n * S
```

## Supported architectures
The current implementation uses the `scikit-learn` framework. The architectures considered are:

|                   | Standard deviation source           | How it reaches the ONNX model |
| ----------------- | ----------------------------------- | ------------------- |
| `bayesian_ridge`  | Bayesian posterior std              | exact formula is appended as ONNX nodes (skl2onnx's own converter has problems, see below) |
| `random_forest`   | spread across trees, calibrated     | emit one target per tree then aggregate |
| `extra_trees`     | spread across trees, calibrated     | emit one target per tree then aggregate |

Specifically excluded are:

- Gaussian process regression. It supports a posterior standard deviation, but `O(N^3)` training
  cannot use a meaningful fraction of the `N` ~ 2 million-cell atlas.
- Boosting and purely-mean regressors (ridge, elastic net, huber, gradient boosting,
  XGBoost). The standard deviation is either a single residual scale or, for additive boosting,
  has no meaningful across-tree spread.

The workflow is currently verified for library versions: skl2onnx 1.20, onnxruntime 1.23, scikit-learn 1.9, onnx 1.22.

## BayesianRidge: skl2onnx's `return_std` is unreliable
skl2onnx's built-in `return_std` converter for the BayesianRidge architecture uses a
linear form where a certain quadratic form is needed. See issue [#455](#455).

## Tree ensembles: per-tree spread as a calibrated std
A random forest has no typically-computed posterior standard deviation; its natural
uncertainty is the spread of its trees' predictions. skl2onnx converts the forest to
a single `TreeEnsembleRegressor` that sums each tree's final node weight into one target,
so its output is only the mean. By introspecting the trained model, we re-emit with
**one target per tree**, and mean and spread are then both computed from these (`_append_tree_ensemble_std`).

**Size.** We train using 100 trees with `max_depth=8` and `min_samples_leaf=100`, which
keeps a model at a few MB at most. The export logs a warning above 5 MB. These bounds
are a first approximation and should be revisited after a full-data run.

## Validation
`validate_onnx` runs each exported model on original rows held out and compares the models
trained with 3 different architectures against the numpy/sklearn reference.

The unit tests in `test/atlas/unit_tests/test_atlas_inference.py` assert numeric
concordance between the sklearn model and the ONNX model.

## Where the code lives

- [`smprofiler/atlas/model_selection_fitting.py`](smprofiler/atlas/model_selection_fitting.py): candidates, CV selection, tree calibration.
- [`smprofiler/atlas/artifacts.py`](smprofiler/atlas/artifacts.py): export to ONNX, the appended subgraphs, the in-graph normalization and z-score, ONNX validation.
- [`smprofiler/atlas/inference.py`](smprofiler/atlas/inference.py): prediction and thresholding.
- [`smprofiler/atlas/training.py`](smprofiler/atlas/training.py): End-to-end run.
- [`smprofiler/db/accessors/atlas_models.py`](smprofiler/db/accessors/atlas_models.py): API access to models.
- [`smprofiler/apiserver/app/main.py`](smprofiler/apiserver/app/main.py): API access to models.

