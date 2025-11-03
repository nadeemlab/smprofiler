"""Data types to support the automated analysis."""
from typing import Literal
from typing import cast
from math import log10
from itertools import chain
import re

from attrs import define
from attrs import field
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
    phenotype_str: str
    other_str: str

    @classmethod
    def _form_phenotype_str(cls, phenotype: PhenotypeCriteria) -> str:
        if phenotype is None:
            return None
        return ' '.join(chain(
            map(lambda m: cls._sanitize_channel(m) + '+', phenotype.positive_markers),
            map(lambda m: cls._sanitize_channel(m) + '-', phenotype.negative_markers),
        ))

    @classmethod
    def _sanitize_channel(cls, c: str) -> str:
        return re.sub(r'_', ' ', c)

    def get_phenotypes(self) -> tuple[PhenotypeCriteria, ...]:
        return cast(tuple[PhenotypeCriteria, ...], tuple(
            filter(
                lambda p0: p0 is not None,
                [self.phenotype, self.other]
            )
        ))

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
class ReportCohort:
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
    report_cohorts: tuple[ReportCohort, ReportCohort]

    @classmethod
    def _form_report_cohorts(cls, higher_cohort: str, lower_cohort: str, key: dict[str, ReportCohort]) -> tuple[ReportCohort, ReportCohort]:
        return (key[higher_cohort], key[lower_cohort])

    @classmethod
    def _find_lower_cohort(cls, case: Case, higher_cohort: str) -> str:
        return list(set(case.cohorts).difference([higher_cohort]))[0]

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

@define
class ReportStudyMetadata:
    study_description_phrase: str
    cohorts: tuple[ReportCohort, ...]
    number_cohorts_plus_one: int
    number_samples: int
    main_author: str
    reference_footnote: str
    data_collection_modality: str
    number_channels: int
    date_generated: str
    cohorts_by_key: dict[str, ReportCohort]

@define
class AnalysisSummary:
    results: FilteredResults
    highlights: Highlights
    metadata: ReportStudyMetadata


