"""Model artifact production: ONNX export, ONNX validation, and metadata.

Converts a fitted estimator to ONNX (via skl2onnx), appends the per-sample
standard deviation and the z-score computation as ONNX nodes, verifies the
exported graph reproduces the sklearn reference within tolerance, and writes the
per-model JSON metadata.

Exported graph contract (all tensors float32):

- inputs: ``X`` of shape ``(n_cells, n_identity)``, raw identity-marker
  intensities in ``input_channels`` order; ``measured`` of shape ``(n_cells,)``,
  raw intensity of the target functional marker.
- outputs: ``z`` (primary), ``mean``, ``std``, each of shape ``(n_cells,)``.
  ``mean`` and ``std`` are on the raw intensity scale. Cells whose identity row
  sums to zero have no atlas reference and yield ``NaN`` in all three.

The identity-sum normalization used at training time is performed inside the
graph, so callers pass raw values and treat the model as a black box.

How the std reaches the graph depends on the architecture:

- BayesianRidge: skl2onnx's ``return_std`` converter drops the element-wise
  ``* X`` from sklearn's ``(X @ sigma_ * X).sum(1)`` and is therefore wrong (see
  ``docs/skl2onnx_bayesian_ridge_std_bug.md``). The exact formula is appended as
  nodes instead (:func:`_append_bayesian_ridge_std`).
- RandomForest / ExtraTrees: skl2onnx emits one ``TreeEnsembleRegressor`` that
  outputs only the mean. It is re-emitted with one target per tree, and the mean
  and calibrated spread are computed from the per-tree predictions
  (:func:`_append_tree_ensemble_std`).
"""
import json
from pathlib import Path
from typing import cast

import numpy as np
from numpy.typing import NDArray
from onnx import AttributeProto, ModelProto, TensorProto, checker, helper, numpy_helper
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType
from skl2onnx.common.data_types import FloatTensorType
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import BayesianRidge
from onnxruntime import InferenceSession
from onnxruntime import SessionOptions  # type: ignore  # conditionally imported due to c binding under the hood

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.model_selection_fitting import predict_with_std

logger = colorized_logger(__name__)

ONNX_INPUT_NAMES = ('X', 'measured')
ONNX_OUTPUT_NAMES = ('z', 'mean', 'std')

# Opset pins: ReduceSum/Unsqueeze with axes as an input need the default domain at
# 13 or later; ai.onnx.ml 3 keeps TreeEnsembleRegressor (not the newer TreeEnsemble).
_TARGET_OPSET = {'': 17, 'ai.onnx.ml': 3}

_MEAN_RELATIVE_L1_TOLERANCE = 1e-3
_STD_RTOL = 1e-2
_STD_ATOL = 1e-6
_Z_RTOL = 1e-2
_Z_ATOL = 1e-3
_SIZE_WARNING_BYTES = 5_000_000


def export_to_onnx(
    model,
    model_name: str,
    number_features: int,
    output_path: Path,
    double_precision: bool = False,
    *,
    tree_calibration: float = 1.0,
) -> None:
    """
    Convert a fitted candidate pipeline to ONNX with the (X, measured) -> (z, mean, std)
    contract described in the module docstring, and save it.

    `tree_calibration` is the γ factor for the tree ensembles' spread (see
    `model_selection_fitting._tree_std_calibration`); ignored for BayesianRidge.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tensor_type = DoubleTensorType if double_precision else FloatTensorType
    initial_type = [('X', tensor_type([None, number_features]))]
    onnx_model = cast(ModelProto, convert_sklearn(model, initial_types=initial_type, target_opset=_TARGET_OPSET))

    estimator = model.steps[-1][1] if hasattr(model, 'steps') else model
    if isinstance(estimator, BayesianRidge):
        _append_bayesian_ridge_std(onnx_model, model, double_precision)
    elif isinstance(estimator, (RandomForestRegressor, ExtraTreesRegressor)):
        _append_tree_ensemble_std(onnx_model, model, tree_calibration, double_precision)
    else:
        raise ValueError(f'No ONNX std path for model "{model_name}" ({type(estimator).__name__}).')
    _prepend_row_sum_normalization_and_z(onnx_model, double_precision)
    _deduplicate_opset_imports(onnx_model)
    checker.check_model(onnx_model)

    with open(output_path, 'wb') as f:
        f.write(onnx_model.SerializeToString())
    size_bytes = output_path.stat().st_size
    logger.info('ONNX model saved: %s (%.1f KB)', output_path, size_bytes / 1024)
    if size_bytes > _SIZE_WARNING_BYTES:
        logger.warning('ONNX model is %.1f MB; consider tighter tree bounds.', size_bytes / 1e6)


def _deduplicate_opset_imports(onnx_model: ModelProto) -> None:
    """skl2onnx can list the default domain twice when given a dict target opset."""
    seen: dict[str, int] = {}
    for entry in onnx_model.opset_import:
        seen[entry.domain] = max(entry.version, seen.get(entry.domain, 0))
    del onnx_model.opset_import[:]
    for domain, version in seen.items():
        onnx_model.opset_import.append(helper.make_opsetid(domain, version))


def _append_bayesian_ridge_std(onnx_model: ModelProto, model, double_precision: bool) -> None:
    """
    Append the exact per-sample std as a second graph output to a BayesianRidge graph:

        xc  = (X - X_offset_) / X_scale_      # BayesianRidge input-centering
        std = sqrt( sum(xc @ sigma_ * xc, axis=1) + 1/alpha_ )

    Any preceding transform steps in the pipeline are assumed absent (see
    `model_selection_fitting.build_model_candidates`); a StandardScaler, if ever
    reintroduced, is folded into the affine `xc = X * A - B`.
    """
    if hasattr(model, 'steps'):
        scaler = model.steps[0][1] if len(model.steps) > 1 else None
        estimator = model.steps[-1][1]
    else:
        scaler, estimator = None, model
    scaler_mean = scaler.mean_ if scaler is not None else 0.0
    scaler_scale = scaler.scale_ if scaler is not None else 1.0

    np_dtype = np.float64 if double_precision else np.float32
    denominator = scaler_scale * estimator.X_scale_
    affine_scale = (1.0 / denominator).astype(np_dtype)
    affine_offset = (scaler_mean / denominator + estimator.X_offset_ / estimator.X_scale_).astype(np_dtype)
    sigma = estimator.sigma_.astype(np_dtype)
    inverse_alpha = np.array([1.0 / estimator.alpha_], dtype=np_dtype)
    onnx_dtype = TensorProto.DOUBLE if double_precision else TensorProto.FLOAT

    graph = onnx_model.graph
    x_name = graph.input[0].name
    p = 'brstd_'

    def _const(name, array):
        graph.initializer.append(numpy_helper.from_array(array, name=p + name))
        return p + name

    axis = _const('axis', np.array([1], dtype=np.int64))
    graph.node.extend([
        helper.make_node('Mul', [x_name, _const('A', affine_scale)], [p + 'xs']),
        helper.make_node('Sub', [p + 'xs', _const('B', affine_offset)], [p + 'xc']),
        helper.make_node('MatMul', [p + 'xc', _const('sigma', sigma)], [p + 'xS']),
        helper.make_node('Mul', [p + 'xS', p + 'xc'], [p + 'prod']),
        helper.make_node('ReduceSum', [p + 'prod', axis], [p + 'quad'], keepdims=0),
        helper.make_node('Add', [p + 'quad', _const('noise', inverse_alpha)], [p + 'var']),
        helper.make_node('Sqrt', [p + 'var'], [p + 'std']),
    ])
    graph.output.append(helper.make_tensor_value_info(p + 'std', onnx_dtype, [None]))


def _attr_to_py(attr):
    """Decode an ONNX `AttributeProto` to a plain Python value for node re-emission."""
    return {
        AttributeProto.INTS: lambda: list(attr.ints),
        AttributeProto.FLOATS: lambda: list(attr.floats),
        AttributeProto.STRINGS: lambda: [s.decode() for s in attr.strings],
        AttributeProto.INT: lambda: attr.i,
        AttributeProto.FLOAT: lambda: attr.f,
        AttributeProto.STRING: lambda: attr.s.decode(),
    }[attr.type]()


def _append_tree_ensemble_std(
    onnx_model: ModelProto,
    model,
    calibration: float,
    double_precision: bool,
) -> None:
    """
    Replace the single-target `TreeEnsembleRegressor` by one with one target per tree,
    and compute from the per-tree predictions both the mean (written back to the
    original mean output) and a second output

        std = γ · sqrt( mean_k(pred_k²) − mean_k(pred_k)² )

    where γ is `calibration`. Reusing the one tree node keeps the graph about the
    size of the vanilla export.
    """
    estimator = model.steps[-1][1] if hasattr(model, 'steps') else model
    number_trees = len(estimator.estimators_)
    np_dtype = np.float64 if double_precision else np.float32
    onnx_dtype = TensorProto.DOUBLE if double_precision else TensorProto.FLOAT

    graph = onnx_model.graph
    tree_node = next(n for n in graph.node if n.op_type == 'TreeEnsembleRegressor')
    tree_input = tree_node.input[0]
    mean_name = graph.output[0].name
    attributes = {a.name: _attr_to_py(a) for a in tree_node.attribute}
    # skl2onnx pre-divides leaf weights by the number of trees (one SUM target == the
    # mean); multiply back to recover raw per-tree predictions.
    attributes['target_ids'] = list(attributes['target_treeids'])
    attributes['target_weights'] = [w * number_trees for w in attributes['target_weights']]
    attributes['n_targets'] = number_trees
    attributes['aggregate_function'] = 'SUM'
    graph.node.remove(tree_node)

    p = 'tstd_'

    def _const(name, array):
        graph.initializer.append(numpy_helper.from_array(array, name=p + name))
        return p + name

    inverse_n = _const('invn', np.array([1.0 / number_trees], dtype=np_dtype))
    axis = _const('axis', np.array([1], dtype=np.int64))
    graph.node.extend([
        helper.make_node('TreeEnsembleRegressor', [tree_input], [p + 'pertree'], domain='ai.onnx.ml', name=p + 'ter', **attributes),
        helper.make_node('ReduceSum', [p + 'pertree', axis], [p + 'summ'], keepdims=1),
        helper.make_node('Mul', [p + 'summ', inverse_n], [mean_name]),
        helper.make_node('ReduceSum', [p + 'pertree', axis], [p + 'sum0'], keepdims=0),
        helper.make_node('Mul', [p + 'sum0', inverse_n], [p + 'mean0']),
        helper.make_node('Mul', [p + 'pertree', p + 'pertree'], [p + 'sq']),
        helper.make_node('ReduceSum', [p + 'sq', axis], [p + 'sum2'], keepdims=0),
        helper.make_node('Mul', [p + 'sum2', inverse_n], [p + 'meansq']),
        helper.make_node('Mul', [p + 'mean0', p + 'mean0'], [p + 'mean2']),
        helper.make_node('Sub', [p + 'meansq', p + 'mean2'], [p + 'var']),
        helper.make_node('Max', [p + 'var', _const('zero', np.array([0.0], dtype=np_dtype))], [p + 'varc']),
        helper.make_node('Sqrt', [p + 'varc'], [p + 'spread']),
        helper.make_node('Mul', [p + 'spread', _const('gamma', np.array([calibration], dtype=np_dtype))], [p + 'std']),
    ])
    graph.output.append(helper.make_tensor_value_info(p + 'std', onnx_dtype, [None]))


def _prepend_row_sum_normalization_and_z(onnx_model: ModelProto, double_precision: bool) -> None:
    """
    Turn a (X_normalized) -> (mean_normalized, std_normalized) graph into the
    (X, measured) -> (z, mean, std) contract of the module docstring.

    The existing nodes are rewired to read the in-graph normalized identity matrix
    `z_Xn = X / rowsum(X)`. Rows with zero identity sum are divided by 1 instead (so
    the estimator sees finite input) and masked to NaN in all outputs.
    """
    np_dtype = np.float64 if double_precision else np.float32
    onnx_dtype = TensorProto.DOUBLE if double_precision else TensorProto.FLOAT
    graph = onnx_model.graph
    x_name = graph.input[0].name
    mean_normalized_name = graph.output[0].name
    std_normalized_name = graph.output[1].name
    p = 'z_'

    for node in graph.node:
        for i, name in enumerate(node.input):
            if name == x_name:
                node.input[i] = p + 'Xn'

    def _const(name, array):
        graph.initializer.append(numpy_helper.from_array(array, name=p + name))
        return p + name

    axis = _const('axis', np.array([1], dtype=np.int64))
    zero = _const('zero', np.array([0.0], dtype=np_dtype))
    one = _const('one', np.array([1.0], dtype=np_dtype))
    nan = _const('nan', np.array([np.nan], dtype=np_dtype))
    flat = _const('flat', np.array([-1], dtype=np.int64))

    normalization_nodes = [
        helper.make_node('ReduceSum', [x_name, axis], [p + 'S'], keepdims=0),
        helper.make_node('Greater', [p + 'S', zero], [p + 'valid']),
        helper.make_node('Where', [p + 'valid', p + 'S', one], [p + 'Ssafe']),
        helper.make_node('Unsqueeze', [p + 'Ssafe', axis], [p + 'Scol']),
        helper.make_node('Div', [x_name, p + 'Scol'], [p + 'Xn']),
    ]
    z_nodes = [
        helper.make_node('Reshape', [mean_normalized_name, flat], [p + 'mean_n']),
        helper.make_node('Div', ['measured', p + 'Ssafe'], [p + 'measured_n']),
        helper.make_node('Sub', [p + 'measured_n', p + 'mean_n'], [p + 'excess_n']),
        helper.make_node('Div', [p + 'excess_n', std_normalized_name], [p + 'z_raw']),
        helper.make_node('Where', [p + 'valid', p + 'z_raw', nan], ['z']),
        helper.make_node('Mul', [p + 'mean_n', p + 'Ssafe'], [p + 'mean_raw']),
        helper.make_node('Where', [p + 'valid', p + 'mean_raw', nan], ['mean']),
        helper.make_node('Mul', [std_normalized_name, p + 'Ssafe'], [p + 'std_raw']),
        helper.make_node('Where', [p + 'valid', p + 'std_raw', nan], ['std']),
    ]
    existing_nodes = list(graph.node)
    del graph.node[:]
    graph.node.extend(normalization_nodes + existing_nodes + z_nodes)

    graph.input.append(helper.make_tensor_value_info('measured', onnx_dtype, [None]))
    del graph.output[:]
    graph.output.extend(helper.make_tensor_value_info(name, onnx_dtype, [None]) for name in ONNX_OUTPUT_NAMES)


def reference_outputs(
    sklearn_model,
    model_name: str,
    X_raw: NDArray,
    measured_raw: NDArray,
    tree_calibration: float = 1.0,
) -> tuple[NDArray, NDArray, NDArray]:
    """
    The numpy/sklearn reference for the ONNX contract: (z, mean, std) from raw inputs.
    Rows with zero identity sum are NaN.
    """
    X_raw = np.asarray(X_raw, dtype=np.float64)
    measured_raw = np.asarray(measured_raw, dtype=np.float64)
    row_sums = X_raw.sum(axis=1)
    valid = row_sums > 0
    safe_sums = np.where(valid, row_sums, 1.0)
    X_normalized = X_raw / safe_sums[:, np.newaxis]
    mean_normalized, std_normalized = predict_with_std(sklearn_model, model_name, X_normalized, tree_calibration)
    with np.errstate(divide='ignore', invalid='ignore'):
        z = (measured_raw / safe_sums - mean_normalized) / std_normalized
    mean = mean_normalized * safe_sums
    std = std_normalized * safe_sums
    for array in (z, mean, std):
        array[~valid] = np.nan
    return z, mean, std


def validate_onnx(
    onnx_path: Path,
    sklearn_model,
    model_name: str,
    X_raw: NDArray,
    measured_raw: NDArray,
    double_precision: bool = False,
    *,
    tree_calibration: float = 1.0,
) -> tuple[bool, bool]:
    """
    Run the ONNX model on raw inputs and compare (z, mean, std) to the sklearn reference.

    Returns two flags indicating respectively sufficient concordance of the ordinary
    prediction (mean and z) and of the predicted standard deviation.
    """
    options = SessionOptions()
    ERROR_LEVEL = 3
    options.log_severity_level = ERROR_LEVEL
    session = InferenceSession(str(onnx_path), sess_options=options)
    dtype = np.float64 if double_precision else np.float32
    feeds = {'X': np.asarray(X_raw, dtype=dtype), 'measured': np.asarray(measured_raw, dtype=dtype)}
    onnx_z, onnx_mean, onnx_std = (np.asarray(o, dtype=np.float64).reshape(-1) for o in session.run(list(ONNX_OUTPUT_NAMES), feeds))
    z, mean, std = reference_outputs(sklearn_model, model_name, X_raw, measured_raw, tree_calibration)

    mean_difference = float(np.sum(np.abs(onnx_mean - mean)) / max(np.sum(np.abs(mean)), np.finfo(float).tiny))
    mean_concordance = mean_difference < _MEAN_RELATIVE_L1_TOLERANCE
    if not mean_concordance:
        logger.error('ONNX validation, mean vs. sklearn: relative L1 difference = %.6f (tolerated up to %E)', mean_difference, _MEAN_RELATIVE_L1_TOLERANCE)

    std_concordance = bool(np.allclose(onnx_std, std, rtol=_STD_RTOL, atol=_STD_ATOL, equal_nan=True))
    if not std_concordance:
        logger.warning('ONNX validation, std vs. sklearn: max abs difference = %.6f', float(np.nanmax(np.abs(onnx_std - std))))

    z_concordance = bool(np.allclose(onnx_z, z, rtol=_Z_RTOL, atol=_Z_ATOL, equal_nan=True))
    if not z_concordance:
        logger.error('ONNX validation, z vs. sklearn: max abs difference = %.6f', float(np.nanmax(np.abs(onnx_z - z))))

    ordinary_prediction_concordance = mean_concordance and z_concordance
    if ordinary_prediction_concordance and std_concordance:
        logger.info('ONNX validation passed (mean relative L1 = %.2e)', mean_difference)
    return (ordinary_prediction_concordance, std_concordance)


def write_metadata_to_file(
    output_path: Path,
    study: str,
    target_channel: str,
    input_channels: list[str],
    model_type: str,
    cv_r2: float,
    cv_r2_std: float,
    test_r2: float,
    test_mae: float,
    n_train: int,
    n_test: int,
    atlas_version: str,
    sum_normalized: bool = True,
    std_method: str = 'global_residual_std',
    global_std: float = float('nan'),
    onnx_input_dtype: str = 'float32',
    onnx_has_std: bool = True,
    tree_calibration: float = 1.0,
) -> None:
    meta = {
        'study': study,
        'target_channel': target_channel,
        'input_channels': input_channels,
        'model_type': model_type,
        'cv_r2': round(cv_r2, 6),
        'cv_r2_std': round(cv_r2_std, 6),
        'test_r2': round(test_r2, 6),
        'test_mae': round(test_mae, 6),
        'n_train': n_train,
        'n_test': n_test,
        'atlas_version': atlas_version,
        'sum_normalized': sum_normalized,
        'std_method': std_method,
        'global_std': round(float(global_std), 8) if not np.isnan(global_std) else None,
        'onnx_input_dtype': onnx_input_dtype,
        'onnx_has_std': onnx_has_std,
        'onnx_inputs': list(ONNX_INPUT_NAMES),
        'onnx_outputs': list(ONNX_OUTPUT_NAMES),
        'tree_calibration': round(float(tree_calibration), 8),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(meta, f, indent=2)
    logger.info('Metadata saved: %s', output_path)
