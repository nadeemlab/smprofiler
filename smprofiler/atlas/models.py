"""Regression model candidates, cross-validated selection, and prediction.

Only architectures whose predictive standard deviation genuinely depends on the
input ``x`` **and** can be emitted as a native second ONNX output are considered,
so the per-cell z-score computed at inference reads its uncertainty straight from
the ONNX model — no separate Python/pickle path. Concretely:

- ``bayesian_ridge`` — Bayesian posterior predictive std,
- ``gaussian_process`` — GP posterior predictive std.

Both convert with skl2onnx's ``options={<estimator>: {"return_std": True}}`` to a
two-output graph (mean, std). Tree ensembles (random forest / extra trees) were
dropped: their uncertainty is the spread across ``estimators_``, which the ONNX
``TreeEnsembleRegressor`` op collapses and cannot expose. Purely-mean regressors
(ridge, elastic net, huber, gradient boosting) are excluded because they offer
only an input-independent residual std. ``predict_with_std`` raises for any model
outside this set, keeping the invariant enforced in code.

The Gaussian Process uses ``normalize_y=False`` because skl2onnx's ``return_std``
converter crashes on the y-rescaling that ``normalize_y=True`` introduces. To keep
GP fit quality with a zero-mean prior, callers train on **mean-centered** targets
(see :mod:`smprofiler.atlas.training`) and the constant offset is baked back into
the exported ONNX graph (see :func:`smprofiler.atlas.artifacts.export_to_onnx`).
"""
import time

import numpy as np
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

# Models whose predictive std depends on x and exports as a native ONNX output.
STD_METHODS = {
    "bayesian_ridge": "bayesian_posterior",
    "gaussian_process": "gaussian_posterior",
}


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
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (y_mean, y_std) for a fitted model evaluated on normalized inputs.

    y_std is a per-sample predictive std that depends on the input.

    The returned mean/std are on whatever target scale ``model`` was fitted on —
    for the Gaussian Process that is the mean-centered scale (see the module
    docstring); the constant offset is reapplied only in the exported ONNX graph.

    Dispatch rules:
        bayesian_ridge   → posterior predictive std from BayesianRidge.predict()
        gaussian_process → posterior predictive std from GaussianProcessRegressor

    Raises:
        ValueError: for any model whose std would not depend on the input.
    """
    if model_name in STD_METHODS:
        X_scaled = model.named_steps["scaler"].transform(X_norm)
        inner = model.named_steps[model_name]
        y_mean, y_std = inner.predict(X_scaled, return_std=True)
        return y_mean, y_std

    raise ValueError(
        f"Model '{model_name}' has no input-dependent predictive std; only "
        f"{sorted(STD_METHODS)} are supported."
    )
