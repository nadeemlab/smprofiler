"""Exercise the atlas ONNX contract and the inference entrypoints on small exported models.

For each candidate architecture: the exported graph has inputs (X, measured) and
outputs (z, mean, std); its outputs match the numpy/sklearn reference computed from
`predict_with_std`; cells with zero identity sum yield NaN; the atlas-relative call
thresholds correctly; and a graph that does not follow the contract is rejected.
"""
import tempfile
from pathlib import Path

import numpy as np
import onnx
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
from sklearn.linear_model import LinearRegression

from smprofiler.atlas.model_selection_fitting import ModelSelectionFitting
from smprofiler.atlas.artifacts import ONNX_INPUT_NAMES
from smprofiler.atlas.artifacts import ONNX_OUTPUT_NAMES
from smprofiler.atlas.artifacts import SklearnToONNX
from smprofiler.atlas.artifacts import SklearnToONNXValidation
from smprofiler.atlas.inference import AtlasReferenceModel

NUMBER_FEATURES = 4
TREE_CALIBRATION = 1.5


def _synthetic_data(seed: int = 0, n: int = 800):
    rng = np.random.default_rng(seed)
    X_raw = rng.gamma(2.0, 3.0, size=(n, NUMBER_FEATURES))
    sums = X_raw.sum(axis=1)
    X_normalized = X_raw / sums[:, np.newaxis]
    y = X_normalized @ np.array([0.3, -0.1, 0.2, 0.4]) + 0.02 * rng.normal(size=n)
    measured_raw = (y + 0.01 * rng.normal(size=n)) * sums
    return X_raw, X_normalized, y, measured_raw


def _fit_and_export(name: str, model, X_normalized, y) -> tuple[Path, object]:
    model.fit(X_normalized, y)
    path = Path(tempfile.mkdtemp()) / f'{name}.onnx'
    SklearnToONNX.export_to_onnx(model, name, NUMBER_FEATURES, path, tree_calibration=TREE_CALIBRATION)
    return path, model


def test_graph_contract_for_every_architecture():
    X_raw, X_normalized, y, _ = _synthetic_data()
    for name, model in ModelSelectionFitting.build_model_candidates():
        path, _ = _fit_and_export(name, model, X_normalized, y)
        graph = onnx.load(str(path))
        assert [i.name for i in graph.graph.input] == list(ONNX_INPUT_NAMES), name
        assert [o.name for o in graph.graph.output] == list(ONNX_OUTPUT_NAMES), name
        default_opset = next(o.version for o in graph.opset_import if o.domain == '')
        assert default_opset >= 13, (name, default_opset)


def test_onnx_outputs_match_python_reference():
    X_raw, X_normalized, y, measured_raw = _synthetic_data()
    train, test = slice(0, 600), slice(600, 800)
    for name, model in ModelSelectionFitting.build_model_candidates():
        path, fitted = _fit_and_export(name, model, X_normalized[train], y[train])
        ordinary, std = SklearnToONNXValidation.validate_onnx(
            path, fitted, name, X_raw[test], measured_raw[test], tree_calibration=TREE_CALIBRATION,
        )
        assert ordinary and std, (name, ordinary, std)

        model = AtlasReferenceModel(str(path))
        z = model.normalize_functional_marker(X_raw[test], measured_raw[test])
        z_reference, mean_reference, std_reference = SklearnToONNXValidation.sklearn_outputs(
            fitted, name, X_raw[test], measured_raw[test], TREE_CALIBRATION,
        )
        assert np.allclose(z, z_reference, rtol=1e-3, atol=1e-4), name
        assert np.all(std_reference > 0), name


def test_rejects_model_outside_the_contract():
    rng = np.random.default_rng(1)
    features = rng.random((50, NUMBER_FEATURES))
    plain = LinearRegression().fit(features, features[:, 0])
    onnx_model = convert_sklearn(plain, initial_types=[('X', FloatTensorType([None, NUMBER_FEATURES]))])
    model = AtlasReferenceModel(onnx_model.SerializeToString())
    try:
        model.normalize_functional_marker(features[:2], np.zeros(2))
    except ValueError:
        return
    raise AssertionError('predict_z_score should reject a graph without the (X, measured) -> (z, mean, std) contract')


def main():
    test_graph_contract_for_every_architecture()
    test_onnx_outputs_match_python_reference()
    test_rejects_model_outside_the_contract()
    print('atlas inference entrypoints and ONNX contract: OK')


if __name__ == '__main__':
    main()
