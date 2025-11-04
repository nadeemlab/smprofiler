"""Data analysis script with automated multi-feature assessments."""
import re
from typing import cast
from typing import TypeVar
from typing import Callable
from itertools import product
from itertools import combinations
from itertools import chain
from typing import Iterable
import datetime

from pandas import concat
from pandas import DataFrame
from pandas import Series
from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.http_data_accessor import StudyDataAccessor
from smprofiler.db.http_data_accessor import univariate_pair_compare_details as compare
from smprofiler.db.exchange_data_formats.study import Cohort
from smprofiler.db.exchange_data_formats.study import CohortAssignment
from smprofiler.db.exchange_data_formats.study import Publication
from smprofiler.standalone_utilities.log_formats import colorized_logger

from smprofiler.workflow.automated_analysis.types import Case
from smprofiler.workflow.automated_analysis.types import form_result
from smprofiler.workflow.automated_analysis.types import form_reportable_case
from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.types import ReportableResult
from smprofiler.workflow.automated_analysis.types import ReportableCohorts
from smprofiler.workflow.automated_analysis.types import ResultSignificance
from smprofiler.workflow.automated_analysis.types import FilteredResults
from smprofiler.workflow.automated_analysis.types import Highlights
from smprofiler.workflow.automated_analysis.types import AnalysisSummary
from smprofiler.workflow.automated_analysis.types import ReportStudyMetadata
from smprofiler.workflow.automated_analysis.types import ReportableCohort
from smprofiler.workflow.automated_analysis.limits import Limits
from smprofiler.workflow.automated_analysis.limits import DEFAULT_LIMITS
from smprofiler.workflow.automated_analysis.limits import LIMITS_SEVERE
from smprofiler.workflow.automated_analysis.limits import DEFAULT_USAGE_LIMITS
from smprofiler.workflow.automated_analysis.confounding import SimpleConfounding
from smprofiler.workflow.automated_analysis.assessment_logger import AssessmentLogger

logger = colorized_logger(__name__)

T = TypeVar('T')
S = TypeVar('S')

def tuple_map(func: Callable[[T], S], i: Iterable[T]) -> tuple[S, ...]:
    return tuple(map(func, i))

def tuple_filter(func: Callable[[T], bool], i: Iterable[T]) -> tuple[T, ...]:
    return tuple(filter(func, i))

class StudyAutoAssessor(ChainableDestructableResource):
    """
    Automatically search and filter significant results from among, first, elementary
    results involving one phenotype, then incrementally increase the complexity of the
    metrics in the search space, while filtering out additional results which are
    probably confounded by previous ones.
    This uses default limits that trade-off a significance measure and effect size.
    """
    access: StudyDataAccessor
    limits: Limits
    channels: tuple[str, ...]
    cohorts: tuple[str, ...]
    omitted_cohorts: tuple[str, ...]
    number_samples: int
    logger: AssessmentLogger

    def __init__(self, access: StudyDataAccessor, interactive: bool, limits: Limits=DEFAULT_LIMITS, omitted_cohorts: list[str] | None=None):
        self.access = access
        self.limits = limits
        self.omitted_cohorts = tuple(omitted_cohorts) if omitted_cohorts else ()
        self.logger = AssessmentLogger(interactive=interactive)
        self.add_subresource(self.access)
        self.add_subresource(self.logger)

    def get_filtered_results(self) -> AnalysisSummary:
        self._initial_fetch()
        metadata = StudyMetadataPresenter.form_presentation_extracts(self.access, self.omitted_cohorts)
        singleton_significants = self._get_results_from_phase(1, ())
        ratio_significants = self._get_results_from_phase(2, singleton_significants)
        proximity_significants = self._get_results_from_phase(3, singleton_significants)
        def remove_nonfull_data_usage(rs: tuple[Result, ...]) -> tuple[Result, ...]:
            return tuple(filter(lambda r: DEFAULT_USAGE_LIMITS.acceptable(r.significance), rs))
        args = cast(
            tuple[tuple[Result, ...], tuple[Result, ...],tuple[Result, ...]],
            tuple_map(remove_nonfull_data_usage, (singleton_significants, ratio_significants, proximity_significants)),
        )
        results = FilteredResults(*args, self._form_results_dataframe(*args))
        highlights = HighlightExtractor.extract_highlights(results, metadata)
        return AnalysisSummary(results, highlights, metadata)

    def _initial_fetch(self) -> None:
        self.channels = tuple(self.access._retrieve_feature_names())
        cohorts_df = self.access._retrieve_cohorts()
        self.cohorts = tuple(sorted(list(set(cohorts_df['cohort']).difference(set(self.omitted_cohorts))), key=lambda x: int(x)))
        self.number_samples = cohorts_df[cohorts_df['cohort'].apply(lambda x: x not in self.omitted_cohorts)].shape[0]
        self.logger.set_name_width(max(map(len, self.channels)))
        self.logger.log(f'Using channels: {self.channels}')
        self.logger.log(f'Using cohorts: {self.cohorts}')

    def _get_results_from_phase(self, phase: int, previous_results: tuple[Result, ...]):
        results: list[Result] = []
        log = self.logger.get_logging(phase)
        for case in self._get_cases(phase=phase):
            result = self._assess_case(case)
            if not result.significant:
                continue
            if phase == 1:
                results.append(result)
                log(result, ())
                continue
            possible_confounders = tuple(filter(
                lambda r0: SimpleConfounding(r0, result).probable_confounding(),
                previous_results,
            ))
            if len(possible_confounders) == 0:
                results.append(result)
                log(result, possible_confounders)
        return tuple(results)

    def _get_cases(self, phase: int) -> tuple[Case, ...]:
        if phase == 1:
            return tuple_map(
                lambda c: Case(self._form_single_phenotype(c[0]), None, c[1], 'fractions'),
                product(self.channels, combinations(self.cohorts, 2))
            )
        if phase == 2:
            return tuple_map(
                lambda c: Case(self._form_single_phenotype(c[0]), self._form_single_phenotype(c[1]), c[2], 'fractions'),
                filter(
                    lambda c: c[0] != c[1],
                    product(self.channels, self.channels, combinations(self.cohorts, 2))
                )
            )
        if phase == 3:
            return tuple_map(
                lambda c: Case(self._form_single_phenotype(c[0]), self._form_single_phenotype(c[1]), c[2], 'proximity'),
                product(self.channels, self.channels, combinations(self.cohorts, 2)),
            )
        raise ValueError(f'Phase requested: {phase}')

    def _form_single_phenotype(self, channel: str) -> PhenotypeCriteria:
        """
        Special treatment is given to the "distance dichotomized" virtual
        features, to emphasize the case of low value (closer distance).
        """
        if re.search('distance', channel):
            return PhenotypeCriteria(positive_markers=(), negative_markers=(channel,))
        return PhenotypeCriteria(positive_markers=(channel,), negative_markers=())

    def _assess_case(self, case: Case) -> Result:
        handlers = {
            'fractions': self._assess_fraction,
            'proximity': self._assess_proximity,
        }
        return handlers[case.metric](case)

    def _assess_fraction(self, case: Case) -> Result:
        df = self.access.fractions(case.get_phenotypes())
        return self._assess_case_df(df, case, 'fraction')

    def _assess_proximity(self, case: Case) -> Result:
        df = self.access.two_phenotype_spatial_metric(
            'proximity',
            case.get_phenotypes(),
            'proximity',
        )
        return self._assess_case_df(df, case, 'proximity')

    def _assess_case_df(self, df: DataFrame, case: Case, feature_name: str) -> Result:
        cohorts = case.cohorts
        values1 = cast(Series, df[df['cohort'] == cohorts[0]][feature_name])
        values2 = cast(Series, df[df['cohort'] == cohorts[1]][feature_name])
        compare_result = compare(values1, values2)
        p = compare_result.pvalue
        effect = compare_result.effect
        higher_cohort = cohorts[1]
        if effect < 1.0:
            higher_cohort = cohorts[0]
            effect = 1.0 / effect
        N = self.number_samples
        significance = ResultSignificance(float(p), effect, compare_result.fraction_data_used(N))
        return form_result(
            case,
            higher_cohort,
            significance,
            self.limits.acceptable(significance),
        ) 

    def _report_cohorts(self) -> dict[str, ReportableCohort]:
        return self.cohorts_by_key

    def _form_results_dataframe(self, s1: tuple[Result, ...], s2: tuple[Result, ...], s3: tuple[Result, ...]):
        df1 = DataFrame([self._form_result_record(r) for r in s1])
        df1['metric'] = 'fraction'
        df2 = DataFrame([self._form_result_record(r) for r in s2])
        df2['metric'] = 'ratio'
        df3 = DataFrame([self._form_result_record(r) for r in s3 if LIMITS_SEVERE.acceptable(r.significance)])
        df3['metric'] = 'proximity'
        df = concat([df1, df2, df3], axis=0)
        return df

    def _form_result_record(self, r: Result) -> dict[str, str | float | int]:
        return {
            'multiplier': r.significance.effect,
            'p': r.significance.p,
            'higher_cohort': r.higher_cohort,
            'c1': r.case.cohorts[0],
            'c2': r.case.cohorts[1],
            'p1': self.logger._format_phenotype(r.case.phenotype),
            'p2': self.logger._format_phenotype(r.case.other) if r.case.other else '',
            'quality': r.quality(),
        }


class StatementAugmentor:
    cohort_details: dict[str, ReportableCohort]

    def __init__(self, cohort_details: dict[str, ReportableCohort]):
        self.cohort_details = cohort_details

    def augment(self, result: Result) -> ReportableResult:
        return self._form_reportable_result(result, self._generate_statement(result))

    def _generate_statement(self, result: Result) -> str:
        cohorts = self._reportable_cohorts(result)
        case = form_reportable_case(result.case)
        effect = AssessmentLogger._format_effect(result.significance.effect)
        p = AssessmentLogger._format_p(result.significance.p)
        if result.case.metric == 'fractions':
            if result.case.other is None:
                return fr'The overall fraction of {case.phenotype_str} cells is elevated by {effect} times in \textbf{{{cohorts.higher_cohort.abbreviation}}} samples compared with \textbf{{{cohorts.lower_cohort.abbreviation}}} samples, the difference being significant at level ${p}$ by the t-test.'
            else:
                return fr'The ratio of {case.phenotype_str} cells to {case.other_phenotype_str} cells is elevated by {effect} times in \textbf{{{cohorts.higher_cohort.abbreviation}}} samples compared with \textbf{{{cohorts.lower_cohort.abbreviation}}} samples, the difference being significant at level ${p}$ by the t-test.'
        return ''

    def _reportable_cohorts(self, result: Result) -> ReportableCohorts:
        return ReportableCohorts(
            self.cohort_details[result.higher_cohort],
            self.cohort_details[result.lower_cohort],
        )

    def _form_reportable_result(self, result: Result, statement: str) -> ReportableResult:
        return ReportableResult(
            result,
            form_reportable_case(result.case),
            self._reportable_cohorts(result),
            statement,
        )


class HighlightExtractor:
    @classmethod
    def extract_highlights(cls, results: FilteredResults, metadata: ReportStudyMetadata) -> Highlights:
        extracted: list[tuple[Result, ...]] = []
        by_metric: list[tuple[Result, ...]] = []
        for results_metric in (results.single_fractions, results.ratios, results.proximity):
            results25 = cls.get_top(25, results_metric)
            pared = cls.remove_common_patterns(results25)
            extracted.append(pared)
            by_metric.append(cls.get_top(10, pared))
        top3 = cls.get_top(3, tuple(chain(*extracted)))
        by_metric = list(map(lambda t: cls.remove_specific_set(top3, t), extracted))
        by_metric = list(map(lambda t: cls.get_top(3, t), by_metric))
        a = StatementAugmentor(metadata.cohorts_by_key)
        f = a.augment
        reportables = tuple_map(lambda t: tuple_map(lambda r: f(r), t), by_metric)
        highlights = Highlights(tuple_map(lambda r: f(r), top3), *reportables)
        return highlights

    @classmethod
    def remove_specific_set(cls, specific: tuple[Result, ...], t: tuple[Result, ...]) -> tuple[Result, ...]:
        def compare(r1: Result, r2: Result) -> bool:
            return r1.case == r2.case
        return tuple(filter(lambda r: not any(map(lambda s: compare(s, r), specific)) , t))

    @classmethod
    def get_top(cls, number: int, results: tuple[Result, ...]) -> tuple[Result, ...]:
        sorted_results = sorted(list(results), key=lambda r: -1 * r.quality())
        return tuple(sorted_results[0:number])

    @classmethod
    def find_co_occurring(cls, positively: bool, p: PhenotypeCriteria, results: tuple[Result, ...]) -> tuple[bool, ...]:
        negatively = not positively
        def occurring(r: Result) -> bool:
            if r.case.metric == 'fractions':
                if r.case.phenotype == p and positively:
                    return True
                if r.case.other == p and negatively:
                    return True
            if r.case.metric == 'proximity':
                if r.case.phenotype == p or r.case.other == p and positively:
                    return True
            return False
        return tuple_map(occurring, results)

    @classmethod
    def remove_common_patterns(cls, results: tuple[Result, ...]) -> tuple[Result, ...]:
        phenotypes_occurring = cast(list[PhenotypeCriteria], list(set(map(lambda r: r.case.phenotype, results)).union(set(map(lambda r: r.case.other, results))).difference(set([None]))))
        representatives = []
        pattern_membership = [False for _ in results]
        for p in phenotypes_occurring:
            positively_occurring = cls.find_co_occurring(True, p, results)
            negatively_occurring = cls.find_co_occurring(False, p, results)
            results_p = tuple_map(lambda pair: pair[1], filter(lambda pair: pair[0], zip(positively_occurring, results)))
            results_n = tuple_map(lambda pair: pair[1], filter(lambda pair: pair[0], zip(negatively_occurring, results)))
            if len(results_p) > 2:
                representative = cls.get_top(1, results_p)[0]
                if representative not in representatives:
                    representatives.append(representative)
                pattern_membership = [m1 or m2 for m1, m2 in zip(pattern_membership, positively_occurring)]
            if len(results_n) > 2:
                representative = cls.get_top(1, results_n)[0]
                if representative not in representatives:
                    representatives.append(representative)
                pattern_membership = [m1 or m2 for m1, m2 in zip(pattern_membership, negatively_occurring)]
        results_no_pattern = list(map(lambda pair: pair[1], filter(lambda pair: not pair[0], zip(pattern_membership, results))))
        return tuple(representatives + results_no_pattern)


class CohortSummarizer:
    assignments: list[CohortAssignment]
    use_abbreviation: bool

    def __init__(self, cohorts: list[Cohort], assignments: list[CohortAssignment]):
        self.assignments = assignments
        self._register_cohorts(cohorts)
        self._generate_summaries(cohorts)

    def _register_cohorts(self, cs: list[Cohort]) -> None:
        size = max(map(lambda c: len(c.result), cs))
        self.use_abbreviation = size >= 7

    def _generate_summaries(self, cohorts: list[Cohort]) -> None:
        self.cohorts = tuple_map(self._summarize_cohort, cohorts)
        self.cohorts_by_key = dict(tuple_map(lambda c: (c.identifier, self._summarize_cohort(c)), cohorts))

    def _summarize_cohort(self, c: Cohort) -> ReportableCohort:
        assignments = list(filter(lambda a: a.cohort == c.identifier, self.assignments))
        long_name = ', '.join((c.diagnosis, c.result.lower()))
        if self.use_abbreviation:
            abbreviation = ''.join(map(lambda part: part[0].upper(), filter(lambda part: part not in ['to', 'and', 'of'], re.split(r'[ \-/]', c.result))))
        else:
            abbreviation = c.result
        return ReportableCohort(len(assignments), long_name, abbreviation)

    def get_cohorts(self) -> tuple[ReportableCohort, ...]:
        return self.cohorts

    def get_cohorts_by_key(self) -> dict[str, ReportableCohort]:
        return self.cohorts_by_key

class StudyMetadataPresenter:
    @classmethod
    def form_presentation_extracts(cls, access: StudyDataAccessor, omitted_cohorts: tuple[str, ...]) -> ReportStudyMetadata:
        summary = access._retrieve_study_summary()
        s = CohortSummarizer(
            list(filter(lambda c: c.identifier not in omitted_cohorts, summary.cohorts.cohorts)),
            summary.cohorts.assignments,
        )
        cohorts = s.get_cohorts()
        cohorts_by_key = s.get_cohorts_by_key()
        author = summary.products.publication.first_author_name.split(' ')[-1]
        return ReportStudyMetadata(
            access.get_study_name(),
            cohorts,
            len(cohorts) + 1,
            sum(map(lambda c: c.number_samples, cohorts)),
            author,
            cls._form_reference(summary.products.publication, author),
            summary.context.assay.name.lower(),
            summary.counts.channels,
            cls._form_current_date(),
            cohorts_by_key,
        )

    @classmethod
    def _form_current_date(cls) -> str:
        today = datetime.date.today()
        return today.strftime('%b %-d %Y')

    @classmethod
    def _form_reference(cls, p: Publication, author: str) -> str:
        return f'{author} et al. \\href{{{p.url}}}{{{p.title}}} ({p.date})'

