# Atlas model training
## Usage

```sh
smprofiler atlas train-atlas-models \
 --database-config-file=.smprofiler_db.config \
 --save-to-database
```

## Pipeline
The `atlas/` module contains:

- [`AtlasFileRetrieval`](/smprofiler/atlas/atlas_file_retrieval.py). Access specific source cell-atlas files.
- [`ExtractRelevantCellAtlas`](/smprofiler/atlas/extract_relevant_atlas.py). Extract needed information from the cell-atlas.
- [`LoadFromExtraction`](/smprofiler/atlas/extract_relevant_atlas.py). Access to the extraction.
- [`ChannelNamesOrganizer`](/smprofiler/atlas/channel_names_organizer.py). Read SMProfiler channel metadata and prepare it for training purposes.
- [`TrainingOrchestrator`](/smprofiler/atlas/training_orchestrator.py). High-level orchestration of the model training process.
- [`TrainingPlanner`](/smprofiler/atlas/training_planning.py). Form a list of scenarios, one for each model to be trained.
- [`TrainingStudy`](/smprofiler/atlas/training_study). Do training for the markers for one study.
- [`ModelSelectionFitting`](/smprofiler/atlas/model_selection_fitting.py). Actual model fitting, across various architectures.
- [`SklearnToONNX`](/smprofiler/atlas/artifacts.py). Model export to interoperable ONNX format.
- [`SklearnToONNXValidation`](/smprofiler/atlas/artifacts.py). Check concordance with scikit-learn models originally trained.
- [`AtlasReferenceModel`](/smprofiler/atlas/inference.py). Example usage of inference for the ONNX models using the `onnxruntime` Python package.

- Definitions of types used for interoperability between modules:
  * [`CellAtlasSource`](/smprofiler/atlas/types.py)
  * [`InherenceAtlasAnnotatedChannel`](/smprofiler/atlas/types.py)
  * [`TrainingScenarioStudy`](/smprofiler/atlas/types.py)
  * [`TrainingOptions`](/smprofiler/atlas/types.py)
  * [`TrainingProgress`](/smprofiler/atlas/types.py)
  * [`Splits`](/smprofiler/atlas/types.py)
  * [`SelectedModel`](/smprofiler/atlas/types.py)

## What the model outputs
For our atlas-reference models, we deliberately limit ourselves to candidate architectures
whose uncertainty varies non-trivially with input. From raw identity intensities `X` and the raw
measured functional intensity `measured`, every exported graph computes:

```
S      = rowsum(X)
mean   = model(X / S)
std    = predictive std at X / S
z      = ((measured / S) − mean) / std
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
  time cannot use a meaningful fraction of the `N` ~ 2 million-cell atlas.
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

