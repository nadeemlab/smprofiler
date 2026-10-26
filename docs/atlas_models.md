# Atlas-reference models: usage

Atlas-reference models predict, for a "normal" cell with a given **identity**-marker
profile, both the expected intensity of a **functional** marker and the predictive
**standard deviation** of that expectation, with respect to a reference normal dataset
(the Allen Institute Human Immune Health Atlas). The primary per-cell output is the
**z-score**: how many predictive standard deviations the measured intensity sits above
the atlas expectation. A cell is **atlas-relative positive** for the marker when its
z-score exceeds a threshold (`0` = simply above expectation; `2` = a roughly two-sigma,
uncertainty-calibrated call).

Models are small [ONNX](https://onnx.ai) regressors, one per `(study, target_channel)`,
stored in the `atlas_model` database table with metadata and versions. This page
documents how to **use** them; how they are trained is described in
[`smprofiler.atlas`](/smprofiler/atlas) and [`atlas_models_std.md`](atlas_models_std.md).

## Model contract

Every model is a self-contained ONNX graph with two inputs and three outputs, all
`float32`:

| Tensor     | Role   | Shape                      | Meaning |
| ---------- | ------ | -------------------------- | ------- |
| `X`        | input  | `(n_cells, n_identity)`    | **raw** identity-marker intensities, columns in the order of the model's `input_channels` |
| `measured` | input  | `(n_cells,)`               | **raw** measured intensity of the target functional channel |
| `z`        | output | `(n_cells,)`               | z-score `(measured − expected) / std` — the primary result |
| `mean`     | output | `(n_cells,)`               | expected target intensity, raw scale |
| `std`      | output | `(n_cells,)`               | predictive standard deviation, raw scale |

The identity-sum normalization used during training happens **inside the graph**, so
callers pass raw values and treat the model as a black box. Cells whose identity
intensities sum to zero have no atlas reference: all three outputs are `NaN` for them.

## API

List models for a study (newest version first), optionally for one channel:

```sh
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression"
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression&target_channel=FOXP3"
```

Each item is an [`AtlasModelMetadata`](/smprofiler/db/exchange_data_formats/atlas_models.py):
`id`, `study`, `target_channel`, `input_channels`, `architecture_type`, `std_method`,
`onnx_input_dtype`, `onnx_has_std`, metrics (`cv_r2`, `test_r2`, `test_mae`, `n_train`,
`n_test`), `training_time_seconds`, `size_bytes`, `created`.

Download the ONNX model itself, the latest for `(study, target_channel)` or a specific
`model_id`:

```sh
curl -OJ "https://smprofiler.io/api/atlas-model/?study=LUAD%20progression&target_channel=FOXP3"
```

The body is the ONNX model (`application/octet-stream`). Response headers describe how to
run it: `X-Model-Id`, `X-Onnx-Input-Dtype`, `X-Input-Channels` (comma-separated, the
column order of `X`), `X-Architecture-Type`, `X-Std-Method`, `X-Onnx-Has-Std`.

## Python

```python
import numpy as np
from smprofiler.atlas.inference import load_model, predict_z_score, atlas_relative_positive

# onnx_bytes: e.g. response.content from GET /atlas-model/, or Path(...).read_bytes()
session = load_model(onnx_bytes)

# Raw identity-marker intensities, columns in the model's input_channels order.
identity = np.array([
    [12.0, 3.0, 0.5, 8.0],   # cell 1
    [ 1.0, 9.0, 4.0, 0.2],   # cell 2
])
measured_foxp3 = np.array([2.4, 0.1])   # raw measured target-channel intensity

z = predict_z_score(session, identity, measured_foxp3)
positive = atlas_relative_positive(session, identity, measured_foxp3, threshold=2.0)

# Expected intensity and predictive std on the raw scale, if needed:
from smprofiler.atlas.inference import predict_expected_intensity, predict_expected_std
expected = predict_expected_intensity(session, identity)
spread = predict_expected_std(session, identity)
```

For a whole slide, batch the cells into one `(n_cells, n_identity)` matrix rather than
looping per cell.

## Exposure

The intended use is strictly backend: SMProfiler services compute z-scores and positive
calls and serve those to clients. The model download endpoint and the Python helpers
above are the building blocks for that. The exact contract for exposing results to the
web frontend is still to be agreed (open item, to be discussed with Francisco).
