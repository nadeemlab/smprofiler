# Atlas-reference models usage

## The problem of normalization
It is a challenge to find meaningful normalizations of cell-level multiple-channel
expression data, as it occurs in for example multiplexed proteomics or single-cell RNA-Seq.
Without specially-designed controls, levels for each marker must typically be normalized
across a whole dataset. Thresholds chosen in this regime often result in poor discrimination
of true positives and negatives.

## Atlas-reference models
Large-scale single-cell atlases can be used as the reference, in order to set principled
thresholds for each marker which take into account *all* available cell-identity information
for each individual cell in a given study. Currently we use the Allen Institute Human Immune
Health Atlas[^1].

Our atlas-reference models predict, for a cell with a given **identity**-marker profile,
both the expected intensity of a **functional** marker and the predictive **standard deviation**
of that expectation. They are small [ONNX](https://onnx.ai) models, one per `(study, target_channel)`,
stored in the `atlas_model` database table with metadata and versions. For more
information about how these models are trained, see [`atlas_models_training.md`](atlas_models_training.md).

## Model format
Each model is a self-contained ONNX graph with two inputs and three outputs, trained only
on the channels available for one specific study at a time:

|            |        | Shape                      | Description |
| ---------- | ------ | -------------------------- | ------- |
| `X`        | input  | `(n_cells, n_identity)`    | raw identity-marker intensities, columns in the order of the study's `input_channels` |
| `measured` | input  | `(n_cells,)`               | raw measured intensity of the target functional channel |
| `z`        | output | `(n_cells,)`               | z-score `(measured − expected) / std` |
| `mean`     | output | `(n_cells,)`               | expected target intensity, raw scale |
| `std`      | output | `(n_cells,)`               | predictive standard deviation, raw scale |

Identity-sum normalization is used inside the model to ensure that the overall scale of the
training data is at least coarsely matched against given inputs at runtime. Callers pass raw values and
treat the model as a black box. `NaN` values are assigned to cells whose identity intensities sum to zero.

## API
List models for a study (newest version first), optionally for one channel:

```sh
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression"
curl "https://smprofiler.io/api/atlas-models/?study=LUAD%20progression&target_channel=FOXP3"
```

Each item is an [`AtlasModelMetadata`](/smprofiler/db/exchange_data_formats/atlas_models.py).

Download the ONNX model itself, the latest for `(study, target_channel)` or a specific
`model_id`:

```sh
curl -OJ "https://smprofiler.io/api/atlas-model/?study=LUAD%20progression&target_channel=FOXP3"
```

The body is the ONNX model, and response headers describe how to run it.

## Python API

```python
import numpy as np
from smprofiler.atlas.inference import load_model, predict_z_score, atlas_relative_positive

# onnx_bytes: Model trained on channels for given study and functional marker,
# e.g. response.content from GET /atlas-model/, or Path(...).read_bytes()
session = load_model(onnx_bytes)

# Columns in the input_channels order for the given study, 2 cells and 3 markers:
raw_identity_markers = np.array([
    [12.0, 3.0, 0.5, 8.0],   # cell 1
    [ 1.0, 9.0, 4.0, 0.2],   # cell 2
])

# The measured target-channel intensity for the functional marker (FOXP3 in thise case)
# which is incorporated into the model
measured_foxp3 = np.array([2.4, 0.1])

z = predict_z_score(session, identity, measured_foxp3)
positive = atlas_relative_positive(session, identity, measured_foxp3, threshold=2.0)

# Expected intensity and predictive standard deviation on the raw scale:
from smprofiler.atlas.inference import predict_expected_intensity, predict_expected_std
expected = predict_expected_intensity(session, identity)
spread = predict_expected_std(session, identity)
```

For a whole slide, batch the cells into one `(n_cells, n_identity)` matrix rather than
looping per cell.

## Exposure
The models are intended to be used by the SMProfiler exploratory data analysis application,
and they can be used in any framework or environment that support the usage of ONNX models.

## References
[^1]: Gong Q, Sharma M, Kuan EL, Glass MC, Chander A, Singh M, et al. Longitudinal Multi-omic Immune Profiling Reveals Age-Related Immune Cell Dynamics in Healthy Adults. Nature. 2025. ([paper](https://doi.org/10.1038/s41586-025-09686-5)) ([data](https://apps.allenimmunology.org/aifi/resources/imm-health-atlas/))

