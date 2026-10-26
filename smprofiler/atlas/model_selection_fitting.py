"""
Regression model candidates, cross-validated selection, and prediction with
per-sample standard deviation.

Only architectures whose predictive standard deviation depends on the input
``x`` **and** can be emitted as an ONNX output are candidates:

- ``bayesian_ridge``: Bayesian posterior predictive std.
- ``random_forest`` / ``extra_trees``: spread of the per-tree predictions, scaled
  by a calibration constant fitted on the holdout (see
  :func:`_tree_std_calibration`).

Gaussian process regression is excluded because its O(N^3) training cost cannot
use a meaningful fraction of the ~2M-cell atlas. Boosting and purely-mean
regressors are excluded because their std is either a single residual scale or
has no meaningful across-tree spread.

No ``StandardScaler`` is used: the z-score computed downstream is scale-free, and
the ONNX std subgraph for BayesianRidge folds the estimator's own centering in.
"""
import time

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import BayesianRidge
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import Pipeline
from tqdm import tqdm

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import format_elapsed

logger = colorized_logger(__name__)

# Architecture name -> short code recorded as `std_method` in metadata and the database.
STD_METHODS = {
    'bayesian_ridge': 'bayesian_posterior',
    'random_forest': 'tree_ensemble_spread',
    'extra_trees': 'tree_ensemble_spread',
}

# Architectures whose std is the calibrated spread across `estimators_`.
TREE_METHODS = {'random_forest', 'extra_trees'}

# Bounded tree size keeps the exported TreeEnsembleRegressor at a few MB. Unbounded
# depth on the full atlas would produce graphs of tens to hundreds of MB.
_TREE_PARAMETERS = dict(n_estimators=100, max_depth=8, min_samples_leaf=100, random_state=42, n_jobs=1)


def train_and_select_best(
    X_train: NDArray,
    y_train: NDArray,
    cv_folds: int = 5,
) -> tuple[str, Pipeline, float, float]:
    """
    Train all candidate models with k-fold cross-validation, select the one with highest R².

    Returns:
        (best_model_name, fitted_best_model, cv_r2_mean, cv_r2_std)
    """
    candidates = build_model_candidates()
    bar_format = '  {desc}: {n_fmt}/{total_fmt} [{bar}] {postfix}'
    performances: list[tuple[float, float]] = []
    for name, model_architecture in tqdm(candidates, desc='  CV candidates', leave=False, bar_format=bar_format):
        mean_r2, std_r2, elapsed = _score_architecture_on_data(model_architecture, X_train, y_train, cv_folds)
        logger.info('    %-28s R²=%+.4f ± %.4f  [%s]', name, mean_r2, std_r2, elapsed)
        performances.append((mean_r2, std_r2))
    def key(item: tuple[tuple[str, Pipeline], tuple[float, float]]):
        return item[1][0]
    (best_name, best_model), (best_r2, best_std) = sorted(list(zip(candidates, performances)), key=key, reverse=True)[0]
    logger.info('  → Refitting winner "%s" on full train set…', best_name)
    t0 = time.monotonic()
    best_model.fit(X_train, y_train)
    fitted_best_model = best_model
    elapsed = format_elapsed(time.monotonic() - t0)
    logger.info('  → Done in %s  (CV R²=%.4f ± %.4f)', elapsed, best_r2, best_std)
    return best_name, fitted_best_model, best_r2, best_std


def build_model_candidates() -> list[tuple[str, Pipeline]]:
    """
    Return list of (name, pipeline) for all candidate models.

    The final step of each pipeline is named after the candidate, so
    :func:`predict_with_std` can dispatch on the name. The estimators run
    single-threaded (`n_jobs=1`) because `cross_val_score` already parallelizes
    across folds.
    """
    return [
        ('bayesian_ridge', Pipeline([('bayesian_ridge', BayesianRidge())])),
        ('random_forest', Pipeline([('random_forest', RandomForestRegressor(**_TREE_PARAMETERS))])),
        ('extra_trees', Pipeline([('extra_trees', ExtraTreesRegressor(**_TREE_PARAMETERS))])),
    ]


def _score_architecture_on_data(
    architecture: Pipeline,
    X: NDArray,
    y: NDArray,
    cv_folds: int,
) -> tuple[float, float, str]:
    t0 = time.monotonic()
    scores = cross_val_score(architecture, X, y, cv=cv_folds, scoring='r2', n_jobs=-1)
    mean_r2 = float(scores.mean())
    std_r2 = float(scores.std())
    elapsed = format_elapsed(time.monotonic() - t0)
    return mean_r2, std_r2, elapsed


def predict_with_std(
    model: Pipeline,
    model_name: str,
    X_normalized: NDArray,
    calibration: float = 1.0,
) -> tuple[NDArray, NDArray]:
    """
    Return (mean, std) for a fitted candidate evaluated on sum-normalized inputs.

    The std is per-sample and depends on the input. For the tree ensembles it is
    `calibration` times the spread of the per-tree predictions (`calibration` is
    ignored by BayesianRidge, whose posterior std is already on the predictive
    scale). This is the Python reference that the exported ONNX graph is validated
    against.

    Raises:
        ValueError: for a model outside :data:`STD_METHODS`.
    """
    if model_name not in STD_METHODS:
        raise ValueError(
            f'Model "{model_name}" has no input-dependent predictive std; '
            f'only {sorted(STD_METHODS)} are supported.'
        )
    X_transformed = X_normalized
    for _, step in model.steps[:-1]:
        X_transformed = step.transform(X_transformed)
    estimator = model.steps[-1][1]
    if model_name in TREE_METHODS:
        per_tree = np.column_stack([tree.predict(X_transformed) for tree in estimator.estimators_])
        return per_tree.mean(axis=1), calibration * per_tree.std(axis=1)
    mean, std = estimator.predict(X_transformed, return_std=True)
    return mean, std


def _tree_std_calibration(residuals: NDArray, spread: NDArray) -> float:
    """
    Global scale γ that turns the across-tree spread into a predictive std.

    The raw spread across trees omits the noise term and under-estimates the
    predictive error. Returns `γ = RMS(residual / spread)` over the holdout, so the
    calibrated z-score `residual / (γ·spread)` has approximately unit variance. The
    ratio is winsorized at the 1st/99th percentile to bound the effect of near-zero
    spreads. Falls back to 1.0 when no positive spread is available.
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
