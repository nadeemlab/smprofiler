"""Regression model candidates, cross-validated selection, and prediction.

Only architectures whose predictive standard deviation genuinely depends on the
input ``x`` **and** can be emitted as a second ONNX output are considered, so the
per-cell z-score computed at inference reads its uncertainty straight from the ONNX
model — no separate Python/pickle path. Concretely:

- ``bayesian_ridge`` — Bayesian posterior predictive std,
- ``gaussian_process`` — GP posterior predictive std,
- ``random_forest`` / ``extra_trees`` — spread of the per-tree predictions,
  calibrated to a predictive scale (see below).

BayesianRidge and the GP carry a native posterior std. The tree ensembles expose
only the *epistemic* spread across ``estimators_``; skl2onnx's
``TreeEnsembleRegressor`` collapses that to the mean, so
:mod:`smprofiler.atlas.artifacts` re-emits the trees with one target per tree to
recover the per-tree predictions and computes their std in-graph. That raw spread
under-estimates the predictive std (it omits the noise term), so it is scaled by a
single calibration constant ``γ`` fitted on the holdout
(:func:`_tree_std_calibration`) and baked into the graph. Boosting / purely-mean
regressors (ridge, elastic net, huber, gradient boosting) remain excluded: their
trees are additive, not independent, so there is no meaningful across-tree spread.
``predict_with_std`` raises for any model outside this set.

The Gaussian Process uses ``normalize_y=False`` because skl2onnx's ``return_std``
converter crashes on the y-rescaling that ``normalize_y=True`` introduces. To keep
GP fit quality with a zero-mean prior, callers train on **mean-centered** targets
(see :mod:`smprofiler.atlas.training`) and the constant offset is baked back into
the exported ONNX graph (see :func:`smprofiler.atlas.artifacts.export_to_onnx`).
"""
import time

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel
from sklearn.linear_model import BayesianRidge
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from tqdm import tqdm

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import format_elapsed

logger = colorized_logger(__name__)

# GaussianProcessRegressor is O(n^3) in training-set size; fit it on at most this
# many (randomly sampled) cells. Other candidates train on the full set.
MAX_GP_TRAIN_SAMPLES = 2000

# Models whose predictive std depends on x and is emitted as an ONNX output.
STD_METHODS = {
    "bayesian_ridge": "bayesian_posterior",
    "gaussian_process": "gaussian_posterior",
    "random_forest": "tree_ensemble_spread",
    "extra_trees": "tree_ensemble_spread",
}

# The subset whose std is the calibrated spread across estimators_ (not a native
# posterior); their ONNX std is built by re-emitting the per-tree predictions and
# needs a holdout-fit calibration constant (see _tree_std_calibration).
TREE_METHODS = {"random_forest", "extra_trees"}


def build_model_candidates() -> list[tuple[str, object]]:
    """Return list of (name, sklearn_estimator) for all candidate models.

    Every candidate exposes an input-dependent predictive std via
    :func:`predict_with_std` and a native second ONNX output; see the module
    docstring. The final estimator name in each pipeline matches the candidate
    name so :func:`predict_with_std` can reach it via ``named_steps``.
    """
    gp_kernel = ConstantKernel(1.0) * RBF(length_scale=1.0) + WhiteKernel(noise_level=1.0)
    return [
        (
            "bayesian_ridge",
            Pipeline([
                ("scaler", StandardScaler()),
                ("bayesian_ridge", BayesianRidge()),
            ]),
        ),
        (
            "gaussian_process",
            Pipeline([
                ("scaler", StandardScaler()),
                ("gaussian_process", GaussianProcessRegressor(
                    kernel=gp_kernel,
                    normalize_y=False,  # see module docstring: keeps return_std ONNX export working
                    random_state=42,
                )),
            ]),
        ),
        # The StandardScaler is a no-op for tree splits but keeps the pipeline shape
        # uniform (predict_with_std reaches the estimator via named_steps). 200 trees
        # gives a stable across-tree spread for the std estimate.
        (
            "random_forest",
            Pipeline([
                ("scaler", StandardScaler()),
                ("random_forest", RandomForestRegressor(n_estimators=200, random_state=42)),
            ]),
        ),
        (
            "extra_trees",
            Pipeline([
                ("scaler", StandardScaler()),
                ("extra_trees", ExtraTreesRegressor(n_estimators=200, random_state=42)),
            ]),
        ),
    ]


def _training_data_for(
    name: str,
    X_train: np.ndarray,
    y_train: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Bound the Gaussian Process training set; pass others through unchanged."""
    if name == "gaussian_process" and len(X_train) > MAX_GP_TRAIN_SAMPLES:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(X_train), size=MAX_GP_TRAIN_SAMPLES, replace=False)
        return X_train[idx], y_train[idx]
    return X_train, y_train


def train_and_select_best(
    X_train: np.ndarray,
    y_train: np.ndarray,
    cv_folds: int = 5,
) -> tuple[str, object, float, float]:
    """
    Train all candidate models with k-fold CV, select the one with highest R².

    Returns:
        (best_model_name, fitted_best_model, cv_r2_mean, cv_r2_std)
    """
    candidates = build_model_candidates()
    best_name = None
    best_model = None
    best_r2 = -np.inf
    best_std = np.nan

    for name, model in tqdm(candidates, desc="  CV candidates", leave=False,
                            bar_format="  {desc}: {n_fmt}/{total_fmt} [{bar}] {postfix}"):
        t0 = time.monotonic()
        X_cv, y_cv = _training_data_for(name, X_train, y_train)
        scores = cross_val_score(
            model, X_cv, y_cv,
            cv=cv_folds, scoring="r2", n_jobs=-1,
        )
        mean_r2 = float(scores.mean())
        std_r2 = float(scores.std())
        elapsed = format_elapsed(time.monotonic() - t0)
        marker = " ★" if mean_r2 > best_r2 else ""
        logger.info("    %-28s R²=%+.4f ± %.4f  [%s]%s",
                    name, mean_r2, std_r2, elapsed, marker)

        if mean_r2 > best_r2:
            best_r2 = mean_r2
            best_std = std_r2
            best_name = name
            best_model = model

    # Refit best model on the full training set (subsampled for GP).
    logger.info("  → Refitting winner '%s' on full train set…", best_name)
    t0 = time.monotonic()
    X_fit, y_fit = _training_data_for(best_name, X_train, y_train)
    best_model.fit(X_fit, y_fit)
    logger.info("  → Done in %s  (CV R²=%.4f ± %.4f)",
                format_elapsed(time.monotonic() - t0), best_r2, best_std)
    return best_name, best_model, best_r2, best_std


def predict_with_std(
    model,
    model_name: str,
    X_norm: np.ndarray,
    calibration: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (y_mean, y_std) for a fitted model evaluated on normalized inputs.

    y_std is a per-sample predictive std that depends on the input.

    The returned mean/std are on whatever target scale ``model`` was fitted on —
    for the Gaussian Process that is the mean-centered scale (see the module
    docstring); the constant offset is reapplied only in the exported ONNX graph.

    Dispatch rules:
        bayesian_ridge          → posterior predictive std from BayesianRidge.predict()
        gaussian_process        → posterior predictive std from GaussianProcessRegressor
        random_forest/extra_trees → ``calibration`` × spread of the per-tree predictions

    Args:
        calibration: scale applied to the tree-ensemble spread (γ from
            :func:`_tree_std_calibration`); ignored by the posterior models, which
            already return a calibrated std. Defaults to 1.0 (raw spread).

    Raises:
        ValueError: for any model whose std would not depend on the input.
    """
    if model_name in TREE_METHODS:
        X_scaled = model.named_steps["scaler"].transform(X_norm)
        inner = model.named_steps[model_name]
        per_tree = np.column_stack([tree.predict(X_scaled) for tree in inner.estimators_])
        return per_tree.mean(axis=1), calibration * per_tree.std(axis=1)

    if model_name in STD_METHODS:
        X_scaled = model.named_steps["scaler"].transform(X_norm)
        inner = model.named_steps[model_name]
        y_mean, y_std = inner.predict(X_scaled, return_std=True)
        return y_mean, y_std

    raise ValueError(
        f"Model '{model_name}' has no input-dependent predictive std; only "
        f"{sorted(STD_METHODS)} are supported."
    )


def _tree_std_calibration(residuals: np.ndarray, spread: np.ndarray) -> float:
    """Global scale γ that turns the across-tree spread into a predictive std.

    The raw spread across trees is epistemic-only and under-estimates the predictive
    error. Returns ``γ = RMS(residual / spread)`` over the holdout, so the calibrated
    z-score ``residual / (γ·spread)`` has ~unit variance. The ratio is winsorized at
    the 1st/99th percentile to bound the effect of near-zero spreads; γ falls back to
    1.0 when no positive spread is available (a degenerate all-trees-agree fit).
    """
    residuals = np.asarray(residuals, dtype=np.float64)
    spread = np.asarray(spread, dtype=np.float64)
    positive = spread > 0
    if not positive.any():
        return 1.0
    ratio = residuals[positive] / spread[positive]
    lo, hi = np.percentile(ratio, [1, 99])
    ratio = np.clip(ratio, lo, hi)
    return float(np.sqrt(np.mean(ratio ** 2)))
