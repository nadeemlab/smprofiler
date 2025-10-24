"""Data types to support the automated analysis."""
from typing import Literal
from math import log10

from attrs import define
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
    fraction_data_used: float

    def quality(self) -> float:
        return self.effect * (-1) * log10(self.p)

    def fraction_data_used_defect(self) -> float:
        return 1.0 - self.fraction_data_used

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
class FilteredResults:
    single_fractions: tuple[Result, ...]
    ratios: tuple[Result, ...]
    proximity: tuple[Result, ...]
    dataframe: DataFrame

@define
class Highlights:
    top3: tuple[Result, ...]
    top10: FilteredResults

