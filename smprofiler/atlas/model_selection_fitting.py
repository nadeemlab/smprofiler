"""
Regression model candidates, cross-validated selection, and prediction.
"""
import time

from numpy.typing import NDArray
from sklearn.linear_model import BayesianRidge
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import Normalizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from tqdm import tqdm

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import format_elapsed

logger = colorized_logger(__name__)


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
        logger.info('    %-28s R²=%+.4f ± %.4f  [%s]%s', name, mean_r2, std_r2, elapsed)
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
    Return list of (name, sklearn_estimator) for all candidate models.
    This should include available model architectures for which:

    1. Computational complexity is not prohibitive for sample sizes of order around 100k.
    2. Per-sample standard deviation is an ordinary model output along with (mean) prediction.
    """
    return [
        (
            'bayesian_ridge',
            Pipeline([
                ('normalizer', Normalizer(norm='l1')),
                ('scaler', StandardScaler()),
                ('bayesian_ridge', BayesianRidge()),
            ]),
        ),
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


