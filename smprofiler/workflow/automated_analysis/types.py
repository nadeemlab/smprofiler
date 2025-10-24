"""Data types to support the automated analysis."""
from typing import Literal
from math import log10

from attrs import define
from attrs import field
from numpy import matrix
from numpy import array
from numpy.linalg import inv
from numpy import matmul
from pandas import DataFrame

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria

Metric = Literal['fractions', 'proximity']


@define
class Case:
    """
    In the context of a single-study survey, a single "case" means comparison
    of one or two phenotypes (cell sets) along two given sample cohorts,
    using one of the computed metrics.
    """
    phenotype: PhenotypeCriteria
    other: PhenotypeCriteria | None
    cohorts: tuple[str, str]
    metric: Metric

@define
class ResultSignificance:
    """p-value and multiplicative effect size."""
    p: float
    effect: float

    def quality(self) -> float:
        return self.effect * (-1) * log10(self.p)

@define
class Result:
    """
    One significant result in a specific case. The higher cohort means the
    cohort in which the metric value was higher.
    """
    case: Case
    higher_cohort: str
    significance: ResultSignificance
    significant: bool

    def lower_cohort(self) -> str:
        return list(set(self.case.cohorts).difference([self.higher_cohort]))[0]

    def quality(self) -> float:
        return self.significance.quality()

@define
class Limits:
    """
    Limits for significance involving p value and effect size, enforced with the
    `acceptable` method.
    A highest p-value is enforced, in such a way that it is only allowed to be
    achieved at a given (extreme) effect size.
    Similarly a lowest effect size is enforced, in such a way that it is only
    allowed to be achieved at a given (extreme) p-value.

    Linear interpolation between these two data points of extrema creates the
    threshold of tradeoff between borderline insignificant cases.

    Separately, hard limits (max p-value and min effect size) are also enforced.
    """
    effect_min: float
    p_required_at_effect_min: float
    p_max: float
    effect_required_at_p_max: float
    coefficients: tuple[float, float] = field(init=False)

    def __attrs_post_init__(self):
        self.coefficients = tuple(array(matmul(
            inv(matrix([
                [self.p_max, self.effect_required_at_p_max],
                [self.p_required_at_effect_min, self.effect_min],
            ])),
            matrix([1, 1]).transpose(),
        ).transpose()).tolist()[0])

    def acceptable(self, result: ResultSignificance) -> bool:
        effect = result.effect
        p = result.p
        c = self.coefficients
        linear_term = c[0] * p + c[1] * effect - 1
        return (effect > self.effect_min) and (p < self.p_max) and (linear_term > 0)

DEFAULT_LIMITS = Limits(1.3, 0.01, 0.2, 2.0)
LIMITS_SEVERE = Limits(1.5, 0.005, 0.2, 3.0) 

@define
class FilteredResults:
    single_fractions: tuple[Result, ...]
    ratios: tuple[Result, ...]
    proximity: tuple[Result, ...]
    dataframe: DataFrame

@define
class Highlights:
    top3: tuple[Result, ...]
    top10: FilteredResults

