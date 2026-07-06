"""Regression model candidates, cross-validated selection, and prediction.

Defines the pool of candidate estimators, picks the best by k-fold CV R²,
and computes per-sample predictive std where the winning model supports it
(Bayesian posterior or tree-ensemble variance).
"""
import time

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.linear_model import BayesianRidge, ElasticNet, HuberRegressor, Ridge
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor
from tqdm import tqdm

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import format_elapsed

logger = colorized_logger(__name__)


def build_model_candidates() -> list[tuple[str, object]]:
    """Return list of (name, sklearn_estimator) for all candidate models."""
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
            "ridge",
            Pipeline([
                ("scaler", StandardScaler()),
                ("ridge", Ridge(alpha=1.0)),
            ]),
        ),
        (
            "elastic_net",
            Pipeline([
                ("scaler", StandardScaler()),
                ("enet", ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)),
            ]),
        ),
        (
            "huber",
            Pipeline([
                ("scaler", StandardScaler()),
                ("huber", HuberRegressor(epsilon=1.35, max_iter=200)),
            ]),
        ),
        (
            "bayesian_ridge",
            Pipeline([
                ("scaler", StandardScaler()),
                ("bayesian_ridge", BayesianRidge()),
            ]),
        ),
        (
            "xgboost",
            XGBRegressor(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                tree_method="hist",
                n_jobs=-1,
                random_state=42,
                verbosity=0,
            ),
        ),
    ]


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
        scores = cross_val_score(
            model, X_train, y_train,
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

    # Refit best model on full training set
    logger.info("  → Refitting winner '%s' on full train set…", best_name)
    t0 = time.monotonic()
    best_model.fit(X_train, y_train)
    logger.info("  → Done in %s  (CV R²=%.4f ± %.4f)",
                format_elapsed(time.monotonic() - t0), best_r2, best_std)
    return best_name, best_model, best_r2, best_std


def predict_with_std(
    model,
    model_name: str,
    X_norm: np.ndarray,
) -> tuple[np.ndarray, np.ndarray | None]:
    """
    Return (y_mean, y_std) for a fitted model evaluated on normalized inputs.

    y_std is per-sample predictive std where available, otherwise None
    (caller falls back to global_residual_std stored in metadata).

    Dispatch rules:
        bayesian_ridge  → posterior predictive std from BayesianRidge.predict()
        random_forest / extra_trees → std across individual tree predictions
        all others      → (predictions, None)
    """
    if model_name == "bayesian_ridge":
        X_scaled = model.named_steps["scaler"].transform(X_norm)
        inner = model.named_steps["bayesian_ridge"]
        y_mean, y_std = inner.predict(X_scaled, return_std=True)
        return y_mean, y_std

    if model_name in ("random_forest", "extra_trees"):
        tree_preds = np.stack(
            [t.predict(X_norm) for t in model.estimators_], axis=0
        )  # (n_trees, n_samples)
        return tree_preds.mean(axis=0), tree_preds.std(axis=0)

    return model.predict(X_norm), None
