"""Data types to support the automated analysis."""
from typing import Literal
from typing import cast
from math import log10
from itertools import chain
import re

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

    def get_phenotypes(self) -> tuple[PhenotypeCriteria, ...]:
        return cast(tuple[PhenotypeCriteria, ...], tuple(
            filter(
                lambda p0: p0 is not None,
                [self.phenotype, self.other]
            )
        ))

@define
class ReportableCase:
    metric: Metric
    phenotype_str: str
    other_phenotype_str: str | None

    @classmethod
    def _form_phenotype_str(cls, phenotype: PhenotypeCriteria | None, special_cases: bool=True) -> str | None:
        if phenotype is None:
            return None
        form = ' '.join(chain(
            map(lambda m: cls._sanitize_channel(m) + '+', phenotype.positive_markers),
            map(lambda m: cls._sanitize_channel(m) + '-', phenotype.negative_markers),
        ))
        if special_cases:
            form = cls._handle_special_cases(form)
        return form

    @classmethod
    def _handle_special_cases(cls, form: str) -> str:
        pattern = r'^distance to (\w+)\-$' 
        if re.search(pattern, form):
            return re.sub(pattern, r'\1-near', form)
        return form

    @classmethod
    def _sanitize_channel(cls, c: str) -> str:
        return re.sub(r'_', ' ', c)

def form_reportable_case(case: Case) -> ReportableCase:
    c = ReportableCase._form_phenotype_str
    return ReportableCase(case.metric, cast(str, c(case.phenotype)), c(case.other))

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
class ReportableCohort:
    number_samples: int
    name: str
    abbreviation: str

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
    lower_cohort: str

    @classmethod
    def _find_lower_cohort(cls, case: Case, higher_cohort: str) -> str:
        return list(set(case.cohorts).difference([higher_cohort]))[0]

    def quality(self) -> float:
        return self.significance.quality()

def form_result(case: Case, higher_cohort: str, significance: ResultSignificance, significant: bool) -> Result:
    return Result(case, higher_cohort, significance, significant, Result._find_lower_cohort(case, higher_cohort))

@define
class ReportableCohorts:
    higher_cohort: ReportableCohort
    lower_cohort: ReportableCohort

@define
class ReportableResult:
    base: Result
    case: ReportableCase
    cohorts: ReportableCohorts
    statement: str
    metric_inferred: str
    url: str

@define
class FilteredResults:
    single_fractions: tuple[Result, ...]
    ratios: tuple[Result, ...]
    proximity: tuple[Result, ...]
    dataframe: DataFrame

@define
class Highlights:
    top3: tuple[ReportableResult, ...]
    top10_single_fractions: tuple[ReportableResult, ...]
    top10_ratios: tuple[ReportableResult, ...] 
    top10_proximity: tuple[ReportableResult, ...]

@define
class ReportStudyMetadata:
    study_description_phrase: str
    cohorts: tuple[ReportableCohort, ...]
    number_cohorts: int
    number_samples: int
    main_author: str
    reference_footnote: str
    data_collection_modality: str
    number_channels: int
    cohorts_by_key: dict[str, ReportableCohort]

@define
class AnalysisSummary:
    results: FilteredResults
    highlights: Highlights
    metadata: ReportStudyMetadata


