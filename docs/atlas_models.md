# Atlas-reference models: usage

Atlas-reference models predict, for a "normal" cell with a given **identity**-marker
profile, both the expected intensity of a **functional** marker and the predictive
**standard deviation** of that expectation (trained on the Allen Institute Human Immune
Health Atlas). The primary per-cell output is a **z-score** — how many predictive
standard deviations the measured intensity sits above the atlas expectation. A cell is
**atlas-relative positive** for the marker when its z-score exceeds a threshold (`0` =
simply above expectation; `2` = a ~2-sigma, uncertainty-calibrated call).

Models are small ONNX regressors, one per `(study, target_channel)`, stored in the
`atlas_model` database table (with metadata and versions). This page documents how to
**use** them; for how they are trained see `smprofiler.atlas`.

Every model:
- takes one input tensor named `X`, shape `(n_cells, n_identity)`, columns in the order
  of the model's `input_channels`;
- expects inputs **sum-normalized** by each cell's identity-marker row sum (the helpers
  below do this for you);
- has **two outputs** on that normalized scale: the expected functional intensity
  (output index 0) and a per-sample predictive std (output index 1) — the z-score is
  `(measured − expected) / std`, and the normalization scale cancels;
- uses input dtype `float32`, except Gaussian-Process models which use `float64` (given
  by `onnx_input_dtype` in the metadata / the `X-Onnx-Input-Dtype` header).

## API

List models for a study (newest version first), optionally for one channel:

```sh
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression"
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression&target_channel=FOXP3"
```

Each item is `AtlasModelMetadata`: `id`, `study`, `target_channel`, `input_channels`,
`architecture_type`, `std_method`, `onnx_input_dtype`, `onnx_has_std`, metrics (`cv_r2`,
`test_r2`, `test_mae`, `n_train`, `n_test`), `training_time_seconds`, `size_bytes`,
`created`.

Download the ONNX bytes for the latest model (or a specific `model_id`):

```sh
curl -OJ "https://smprofiler.io/api/atlas-model/?study=LUAD%20progression&target_channel=FOXP3"
```

The body is the ONNX model (`application/octet-stream`). Response headers describe how to
run it: `X-Model-Id`, `X-Onnx-Input-Dtype`, `X-Input-Channels` (comma-separated, in input
order), `X-Architecture-Type`, `X-Std-Method`, `X-Onnx-Has-Std` (`true` when the graph
has the second, std output).

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

# Primary output: per-cell z-score (std deviations above the atlas expectation).
z = predict_z_score(session, identity, measured_foxp3)

# Boolean call. threshold=0 -> above expectation; threshold=2 -> ~2-sigma call.
positive = atlas_relative_positive(session, identity, measured_foxp3, threshold=2.0)

# Or get the expected intensity directly (same raw scale as `measured`):
from smprofiler.atlas.inference import predict_expected_intensity
expected = predict_expected_intensity(session, identity)
```

Pass **raw** intensities — normalization is handled internally to match training. Cells
whose identity intensities sum to zero have no reference (`z` and `expected` are `NaN`,
`positive` is `False`).

## JavaScript (browser, onnxruntime-web)

```js
import * as ort from 'onnxruntime-web';

// 1. Fetch the model + the metadata needed to run it.
const study = 'LUAD progression', channel = 'FOXP3';
const response = await fetch(
  `/api/atlas-model/?study=${encodeURIComponent(study)}&target_channel=${encodeURIComponent(channel)}`
);
const inputDtype = response.headers.get('X-Onnx-Input-Dtype');        // 'float32' | 'float64'
const inputChannels = response.headers.get('X-Input-Channels').split(',');
const session = await ort.InferenceSession.create(new Uint8Array(await response.arrayBuffer()));

// 2. Score one cell. `cellIdentity` is raw intensities in `inputChannels` order.
//    Returns the z-score: std deviations above the atlas expectation (NaN = no reference).
async function atlasZScore(cellIdentity, measuredFunctional) {
  const rowSum = cellIdentity.reduce((a, b) => a + b, 0);
  if (rowSum <= 0) return NaN;                                        // no reference
  const normalized = cellIdentity.map(v => v / rowSum);              // match training

  const ArrayType = inputDtype === 'float64' ? Float64Array : Float32Array;
  const input = new ort.Tensor(inputDtype, ArrayType.from(normalized), [1, normalized.length]);

  const outputs = await session.run({ [session.inputNames[0]]: input });   // input name is 'X'
  const predictedNormalized = outputs[session.outputNames[0]].data[0];     // mean  (output 0)
  const stdNormalized = outputs[session.outputNames[1]].data[0];           // std   (output 1)
  // Scale cancels: z = (measured/rowSum - predicted) / std.
  return (measuredFunctional / rowSum - predictedNormalized) / stdNormalized;
}

// atlas-relative positive at a 2-sigma threshold:
const positive = (await atlasZScore(cell, measured)) > 2.0;
```

For a whole slide, batch the cells into one `(n_cells, n_identity)` tensor rather than
looping per cell.
