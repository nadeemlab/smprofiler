"""Model artifact production: ONNX export, ONNX validation, and metadata.

Converts a fitted estimator to ONNX (via skl2onnx), verifies the exported model
reproduces the sklearn predictions within tolerance, and writes the per-model
JSON metadata sidecar.

Every atlas model is exported with ``return_std=True`` so the ONNX graph has a
**second output**: a per-sample predictive std alongside the mean. Inference reads
both to produce a z-score, so uncertainty lives entirely in the ONNX file (see
:mod:`smprofiler.atlas.inference`). How the std output is produced depends on the
architecture:

- Gaussian Process: skl2onnx's ``return_std`` converter is exact (matches sklearn
  to ~1e-8 in float64), so we use it directly.
- BayesianRidge: skl2onnx's ``return_std`` converter is systematically wrong for a
  ``StandardScaler → BayesianRidge`` pipeline — off by 1–2% on well-conditioned
  data and 20%+ when ill-conditioned — so we ignore it and append the exact
  formula ``std = sqrt(xc·Σ·xc + 1/alpha_)`` as ONNX nodes instead
  (:func:`_append_bayesian_ridge_std`), which reproduces sklearn bit-for-bit.

Gaussian Process predictions involve kernel-matrix inversion and only reproduce
in double precision (float32 is off by a few percent), so GP models are exported
and run with float64 inputs; the others use float32. Callers pass
``double_precision`` and record the choice in the metadata (``onnx_input_dtype``)
so inference feeds the matching dtype.

When the model was fitted on mean-centered targets (the GP path — see the
:mod:`smprofiler.atlas.models` docstring), pass ``target_offset`` so the constant
is added back to the mean output inside the ONNX graph; the exported model then
predicts on the original target scale and inference needs no offset knowledge. The
std output is shift-invariant and is left untouched.
"""
import json
from pathlib import Path

import numpy as np
from onnx import ModelProto, TensorProto, helper, numpy_helper
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import DoubleTensorType, FloatTensorType
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.linear_model import BayesianRidge
from onnxruntime import InferenceSession, SessionOptions

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

# Mean reproduces to ~1e-6 or better; std, once produced by the exact paths above,
# reproduces to float precision. The std check is relative so it still flags a
# regression to skl2onnx's ~1-2%-off BayesianRidge converter.
_MEAN_TOL = 1e-3
_STD_RTOL = 1e-2
_STD_ATOL = 1e-4


def _bake_target_offset(onnx_model: ModelProto, offset: float, double_precision: bool) -> None:
    """Add ``offset`` to the model's first (mean) output, in place.

    Renames the tensor currently produced for the mean output and appends an
    ``Add`` node that writes the original output name, so the graph's declared
    outputs (names, types, shapes) are unchanged — only their values shift by the
    constant. Used to reapply the training-target mean that the GP was centered by.
    """
    graph = onnx_model.graph
    mean_name = graph.output[0].name
    raw_name = f"{mean_name}_precentered"
    for node in graph.node:
        for i, out in enumerate(node.output):
            if out == mean_name:
                node.output[i] = raw_name
    onnx_dtype = np.float64 if double_precision else np.float32
    graph.initializer.append(
        numpy_helper.from_array(np.array([offset], dtype=onnx_dtype), name=f"{mean_name}_offset")
    )
    graph.node.append(
        helper.make_node(
            "Add", inputs=[raw_name, f"{mean_name}_offset"], outputs=[mean_name],
            name="add_target_offset",
        )
    )


def _append_bayesian_ridge_std(onnx_model: ModelProto, model, double_precision: bool) -> None:
    """Append an exact per-sample std as a second output to a BayesianRidge graph.

    Computes sklearn's predictive-std formula directly as ONNX nodes::

        xc  = (scaler(X) - X_offset_) / X_scale_      # BayesianRidge input-centering
        std = sqrt( sum(xc @ sigma_ * xc, axis=1) + 1/alpha_ )

    reading the graph input ``X`` and folding the optional preceding ``StandardScaler``
    and the BayesianRidge centering into one affine ``xc = X * A - B``. This matches
    sklearn to float precision, unlike skl2onnx's own ``return_std`` for BayesianRidge
    (see the module docstring). ``model`` is the fitted estimator or pipeline whose
    final step is the BayesianRidge.
    """
    if hasattr(model, "steps"):
        scaler = model.steps[0][1] if len(model.steps) > 1 else None
        estimator = model.steps[-1][1]
    else:
        scaler, estimator = None, model
    sc_mean = scaler.mean_ if scaler is not None else 0.0
    sc_scale = scaler.scale_ if scaler is not None else 1.0

    np_dtype = np.float64 if double_precision else np.float32
    denom = sc_scale * estimator.X_scale_
    affine_scale = (1.0 / denom).astype(np_dtype)                      # per-feature multiplier A
    affine_offset = (sc_mean / denom + estimator.X_offset_ / estimator.X_scale_).astype(np_dtype)
    sigma = estimator.sigma_.astype(np_dtype)
    inv_alpha = np.array([1.0 / estimator.alpha_], dtype=np_dtype)
    onnx_dtype = TensorProto.DOUBLE if double_precision else TensorProto.FLOAT

    graph = onnx_model.graph
    x_name = graph.input[0].name
    p = "brstd_"  # node/initializer name prefix, kept clear of skl2onnx's own names

    def _const(name, arr):
        graph.initializer.append(numpy_helper.from_array(arr, name=p + name))
        return p + name

    graph.initializer.append(numpy_helper.from_array(np.array([1], dtype=np.int64), name=p + "axis"))
    graph.node.extend([
        helper.make_node("Mul", [x_name, _const("A", affine_scale)], [p + "xs"]),
        helper.make_node("Sub", [p + "xs", _const("B", affine_offset)], [p + "xc"]),
        helper.make_node("MatMul", [p + "xc", _const("sigma", sigma)], [p + "xS"]),
        helper.make_node("Mul", [p + "xS", p + "xc"], [p + "prod"]),
        helper.make_node("ReduceSum", [p + "prod", p + "axis"], [p + "quad"], keepdims=0),
        helper.make_node("Add", [p + "quad", _const("noise", inv_alpha)], [p + "var"]),
        helper.make_node("Sqrt", [p + "var"], [p + "std"]),
    ])
    graph.output.append(helper.make_tensor_value_info(p + "std", onnx_dtype, [None]))


def export_to_onnx(
    model,
    n_features: int,
    output_path: Path,
    double_precision: bool = False,
    *,
    return_std: bool = False,
    target_offset: float = 0.0,
) -> None:
    """Convert a fitted sklearn estimator / pipeline to ONNX and save.

    Args:
        model: fitted estimator or ``Pipeline`` (final step is the estimator).
        n_features: width of the single input tensor ``X``.
        output_path: destination ``.onnx`` file.
        double_precision: export a float64-input model (required for GP).
        return_std: also emit a per-sample predictive std as a second ONNX output.
            Supported for GaussianProcessRegressor (via skl2onnx) and BayesianRidge
            (via an exact appended subgraph); raises for anything else.
        target_offset: constant added to the mean output inside the graph, to undo
            target mean-centering done before fitting (0.0 = no-op).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tensor_type = DoubleTensorType if double_precision else FloatTensorType
    initial_type = [("X", tensor_type([None, n_features]))]
    final_estimator = model.steps[-1][1] if hasattr(model, "steps") else model

    if return_std and isinstance(final_estimator, GaussianProcessRegressor):
        # skl2onnx's GP return_std is exact; emit its native second output.
        onnx_model = convert_sklearn(
            model, initial_types=initial_type,
            options={GaussianProcessRegressor: {"return_std": True}},
        )
    elif return_std and isinstance(final_estimator, BayesianRidge):
        # skl2onnx's BayesianRidge return_std is inaccurate; export mean-only and
        # append the exact std formula ourselves.
        onnx_model = convert_sklearn(model, initial_types=initial_type)
        _append_bayesian_ridge_std(onnx_model, model, double_precision)
    elif return_std:
        raise ValueError(
            f"return_std is not supported for {type(final_estimator).__name__}; "
            "only GaussianProcessRegressor and BayesianRidge."
        )
    else:
        onnx_model = convert_sklearn(model, initial_types=initial_type)

    if target_offset:
        _bake_target_offset(onnx_model, target_offset, double_precision)
    with open(output_path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    size_kb = output_path.stat().st_size / 1024
    logger.info("ONNX model saved: %s (%.1f KB)", output_path, size_kb)


def validate_onnx(
    onnx_path: Path,
    sklearn_model,
    X_sample: np.ndarray,
    double_precision: bool = False,
    *,
    target_offset: float = 0.0,
    expected_std: np.ndarray | None = None,
) -> bool:
    """
    Run the ONNX model and compare output(s) to sklearn's predictions.

    Compares the mean output against ``sklearn_model.predict(X) + target_offset``
    (the offset mirrors what :func:`export_to_onnx` baked into the graph). When
    ``expected_std`` is given, also checks the second (std) output against it.
    Returns True if every compared output matches within tolerance.
    """
    ort_opts = SessionOptions()
    ort_opts.log_severity_level = 3  # 0=VERBOSE … 3=ERROR (onnxruntime's own C-level control)
    sess = InferenceSession(str(onnx_path), sess_options=ort_opts)
    dtype = np.float64 if double_precision else np.float32
    outputs = sess.run(None, {"X": X_sample.astype(dtype)})

    onnx_mean = outputs[0].flatten()
    sklearn_mean = sklearn_model.predict(X_sample) + target_offset
    mean_diff = np.abs(onnx_mean - sklearn_mean).max()
    passed = mean_diff <= _MEAN_TOL
    if passed:
        logger.info("ONNX validation passed: mean max abs diff = %.2e", mean_diff)
    else:
        logger.warning("ONNX validation: mean max abs diff = %.6f (tolerated up to %g)",
                        mean_diff, _MEAN_TOL)

    if expected_std is not None:
        if len(outputs) < 2:
            logger.warning("ONNX validation: expected a std output but the model has %d output(s)",
                           len(outputs))
            return False
        onnx_std = np.asarray(outputs[1]).flatten()
        expected = np.asarray(expected_std).flatten()
        std_diff = np.abs(onnx_std - expected).max()
        if np.allclose(onnx_std, expected, rtol=_STD_RTOL, atol=_STD_ATOL):
            logger.info("ONNX validation passed: std max abs diff = %.2e", std_diff)
        else:
            logger.warning("ONNX validation: std max abs diff = %.6f (tolerated rtol=%g atol=%g)",
                           std_diff, _STD_RTOL, _STD_ATOL)
            passed = False
    return passed


def write_metadata(
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
    std_method: str = "global_residual_std",
    global_std: float = float("nan"),
    onnx_input_dtype: str = "float32",
    onnx_has_std: bool = True,
    target_offset: float = 0.0,
) -> None:
    meta = {
        "study": study,
        "target_channel": target_channel,
        "input_channels": input_channels,
        "model_type": model_type,
        "cv_r2": round(cv_r2, 6),
        "cv_r2_std": round(cv_r2_std, 6),
        "test_r2": round(test_r2, 6),
        "test_mae": round(test_mae, 6),
        "n_train": n_train,
        "n_test": n_test,
        "atlas_version": atlas_version,
        "sum_normalized": sum_normalized,
        "std_method": std_method,
        "global_std": round(float(global_std), 8) if not np.isnan(global_std) else None,
        "onnx_input_dtype": onnx_input_dtype,
        # True when the ONNX graph emits a second (per-sample std) output; inference
        # needs it to compute z-scores.
        "onnx_has_std": onnx_has_std,
        # Constant already added back into the ONNX mean output (GP target-centering);
        # recorded for provenance — inference does not need it.
        "target_offset": round(float(target_offset), 8),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Metadata saved: %s", output_path)
