"""Regression model candidates, cross-validated selection, and prediction.

Only architectures whose predictive standard deviation genuinely depends on the
input ``x`` are considered — so that the per-cell "atlas-relative" call can use a
context-aware uncertainty, not a single global residual std. Concretely:

- ``bayesian_ridge`` — Bayesian posterior predictive std,
- ``gaussian_process`` — GP posterior predictive std,
- ``random_forest`` / ``extra_trees`` — spread across the individual trees.

Purely-mean regressors (ridge, elastic net, huber, gradient boosting) are
excluded because they offer only an input-independent residual std.
``predict_with_std`` raises for any model outside this set, keeping the invariant
enforced in code.
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

# Models whose predictive std depends on x (see module docstring).
STD_METHODS = {
    "bayesian_ridge": "bayesian_posterior",
    "gaussian_process": "gaussian_posterior",
    "random_forest": "tree_variance",
    "extra_trees": "tree_variance",
}


def build_model_candidates() -> list[tuple[str, object]]:
    """Return list of (name, sklearn_estimator) for all candidate models.

    Every candidate exposes an input-dependent predictive std via
    :func:`predict_with_std`; see the module docstring.
    """
    gp_kernel = ConstantKernel(1.0) * RBF(length_scale=1.0) + WhiteKernel(noise_level=1.0)
    return [
        (
            "extra_trees",
            ExtraTreesRegressor(
                n_estimators=100,
                max_depth=8,
                n_jobs=-1,
                random_state=42,
            ),
        ),
        (
            "random_forest",
            RandomForestRegressor(
                n_estimators=100,
                max_depth=8,
                n_jobs=-1,
                random_state=42,
            ),
        ),
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
                    normalize_y=True,
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

    Dispatch rules:
        bayesian_ridge   → posterior predictive std from BayesianRidge.predict()
        gaussian_process → posterior predictive std from GaussianProcessRegressor
        random_forest / extra_trees → std across individual tree predictions

    Raises:
        ValueError: for any model whose std would not depend on the input.
    """
    if model_name in ("bayesian_ridge", "gaussian_process"):
        X_scaled = model.named_steps["scaler"].transform(X_norm)
        inner = model.named_steps[model_name]
        y_mean, y_std = inner.predict(X_scaled, return_std=True)
        return y_mean, y_std

    if model_name in ("random_forest", "extra_trees"):
        tree_preds = np.stack(
            [t.predict(X_norm) for t in model.estimators_], axis=0
        )  # (n_trees, n_samples)
        return tree_preds.mean(axis=0), tree_preds.std(axis=0)

    raise ValueError(
        f"Model '{model_name}' has no input-dependent predictive std; only "
        f"{sorted(STD_METHODS)} are supported."
    )
