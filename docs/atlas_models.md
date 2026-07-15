# Atlas-reference models: usage

Atlas-reference models predict the intensity a **functional** marker would have in a
"normal" cell with a given **identity**-marker profile, with respect to a reference
normal dataset. A cell is **atlas-relative positive** for that marker when its
measured intensity exceeds the model's expectation.

Models are small [ONNX](https://onnx.ai) regressors, one per `(study, target_channel)`, stored in the
`atlas_model` database table (with metadata and versions). This page documents how to
**use** them; for how they are trained see [`smprofiler.atlas`](/smprofiler/atlas).

Every model:
- Takes (i) an input matrix of shape `(number_cells, number_identity_markers)`, with columns
  in the order of the model's `input_channels`, and (ii) the functional marker column vector
  of size `number_cells`.
- Expects inputs **sum-normalized** by each cell's identity-marker row sum (the helpers
  below do this for you).
- Returns the standard deviate of the functional marker values relative to expectation.

## API

List models for a study (newest version first), optionally for one channel:

```sh
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression"
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression&target_channel=FOXP3"
```

Each item is `AtlasModelMetadata`: `id`, `study`, `target_channel`, `input_channels`,
`architecture_type`, `std_method`, `onnx_input_dtype`, metrics (`cv_r2`, `test_r2`,
`test_mae`, `n_train`, `n_test`), `training_time_seconds`, `size_bytes`, `created`.

Download the ONNX bytes for the latest model (or a specific `model_id`):

```sh
curl -OJ "https://smprofiler.io/api/atlas-model/?study=LUAD%20progression&target_channel=FOXP3"
```

The body is the ONNX model (`application/octet-stream`). Response headers describe how to
run it: `X-Model-Id`, `X-Onnx-Input-Dtype`, `X-Input-Channels` (comma-separated, in input
order), `X-Architecture-Type`, `X-Std-Method`.

## Python

```python
import numpy as np
from smprofiler.atlas.inference import load_model, atlas_relative_positive

# onnx_bytes: e.g. response.content from GET /atlas-model/, or Path(...).read_bytes()
session = load_model(onnx_bytes)

# Raw identity-marker intensities, columns in the model's input_channels order.
identity = np.array([
    [12.0, 3.0, 0.5, 8.0],   # cell 1
    [ 1.0, 9.0, 4.0, 0.2],   # cell 2
])
measured_foxp3 = np.array([2.4, 0.1])   # raw measured target-channel intensity

positive = atlas_relative_positive(session, identity, measured_foxp3)
# -> array([ True, False])   (True = measured exceeds the atlas expectation)

# Or get the expected intensity directly (same raw scale as `measured`):
from smprofiler.atlas.inference import predict_expected_intensity
expected = predict_expected_intensity(session, identity)
```

Pass **raw** intensities — normalization is handled internally to match training. Cells
whose identity intensities sum to zero have no reference (`expected` is `NaN`, `positive`
is `False`).

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
async function atlasRelativePositive(cellIdentity, measuredFunctional) {
  const rowSum = cellIdentity.reduce((a, b) => a + b, 0);
  if (rowSum <= 0) return false;                                      // no reference
  const normalized = cellIdentity.map(v => v / rowSum);              // match training

  const ArrayType = inputDtype === 'float64' ? Float64Array : Float32Array;
  const input = new ort.Tensor(inputDtype, ArrayType.from(normalized), [1, normalized.length]);

  const outputs = await session.run({ [session.inputNames[0]]: input });   // input name is 'X'
  const predictedNormalized = outputs[session.outputNames[0]].data[0];
  const expected = predictedNormalized * rowSum;                     // back to raw scale
  return measuredFunctional > expected;
}
```

For a whole slide, batch the cells into one `(n_cells, n_identity)` tensor rather than
looping per cell.
