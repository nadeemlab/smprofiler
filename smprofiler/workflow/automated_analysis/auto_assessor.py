"""Data analysis script with automated multi-feature assessments."""
import re
from time import time as time
from typing import cast
from itertools import product
from itertools import combinations
from itertools import chain

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
from smprofiler.standalone_utilities.iteration import tuple_map
from smprofiler.standalone_utilities.iteration import tuple_filter
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
from smprofiler.workflow.automated_analysis.urls import form_url

logger = colorized_logger(__name__)

def powerset(iterable):
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(len(s)+1))

class StudyAutoAssessor(ChainableDestructableResource):
    """
    Automatically search and filter significant results from among, first, elementary
    results involving one phenotype, then incrementally increase the complexity of the
    metrics in the search space, while filtering out additional results which are
    probably confounded by previous ones.
    This uses default limits that trade-off a significance measure and effect size.
    """
    access: StudyDataAccessor
    limits: dict[str, Limits]
    channels: tuple[str, ...]
    cohorts: tuple[str, ...]
    omitted_cohorts: tuple[str, ...]
    omit_proximity: bool
    number_samples: int
    logger: AssessmentLogger

    def __init__(
        self,
        access: StudyDataAccessor,
        omitted_cohorts: list[str] | None=None,
        omitted_channels: list[str] | None=None,
        omit_proximity: bool=False,
    ):
        self.access = access
        self.limits = {'fraction': DEFAULT_LIMITS, 'proximity': LIMITS_SEVERE}
        self.omitted_cohorts = tuple(omitted_cohorts) if omitted_cohorts else ()
        self.omitted_channels = tuple(omitted_channels) if omitted_channels else ()
        self.omit_proximity = omit_proximity
        self.logger = AssessmentLogger(interactive=True)
        self.access.set_logger(self.logger.log)
        self.add_subresource(self.access)
        self.add_subresource(self.logger)

    def get_summary(self) -> AnalysisSummary:
        self._initial_fetch()
        phased_results = self._get_phased_results()
        results = FilteredResults(*phased_results, self._form_results_dataframe(*phased_results))
        metadata = StudyMetadataPresenter.form_presentation_extracts(self.access, self.omitted_cohorts)
        highlights = HighlightExtractor.extract_highlights(results, metadata)
        return AnalysisSummary(results, highlights, metadata)

    def _initial_fetch(self) -> None:
        """
        The initial metadata retrieved in order to form relevant case sets.
        """
        self.channels = tuple(set(self.access._retrieve_feature_names()).difference(set(self.omitted_channels)))
        cohorts_df = self.access._retrieve_cohorts()
        self.cohorts = self._get_relevant_cohorts(cast(Series, cohorts_df['cohort']))
        self.number_samples = cohorts_df[cohorts_df['cohort'].apply(lambda x: x not in self.omitted_cohorts)].shape[0]
        self.logger.set_name_width(max(map(len, self.channels)))
        self.logger.log(f'Using channels: {self.channels}')
        self.logger.log(f'Using cohorts: {self.cohorts}')

    def _get_relevant_cohorts(self, cohorts: Series) -> tuple[str, ...]:
        return tuple(
            sorted(list(
                set(cohorts).difference(set(self.omitted_cohorts))),
                key=lambda x: int(x),
            ),
        )

    def _get_phased_results(
        self,
    ) -> tuple[tuple[Result, ...], tuple[Result, ...],tuple[Result, ...]]:
        singleton_significants = self._get_results_from_phase(1, ())
        ratio_significants = self._get_results_from_phase(2, singleton_significants)
        if not self.omit_proximity:
            proximity_significants = self._get_results_from_phase(3, singleton_significants)
        else:
            proximity_significants = ()
        return cast(
            tuple[tuple[Result, ...], tuple[Result, ...],tuple[Result, ...]],
            tuple_map(
                self._remove_nonfull_data_usage,
                (singleton_significants, ratio_significants, proximity_significants),
            ),
        )

    def _remove_nonfull_data_usage(self, rs: tuple[Result, ...]) -> tuple[Result, ...]:
        """
        Filters out results with suspiciously-high effect size that,
        for whatever reason (e.g. null values for the given computation),
        do not use enough of the whole study's sample set.
        """
        return tuple_filter(lambda r: DEFAULT_USAGE_LIMITS.acceptable(r.significance), rs)

    def _get_results_from_phase(self, phase: int, previous_results: tuple[Result, ...]):
        results: list[Result] = []
        log = self.logger.get_logging(phase)
        cases = self._get_cases(phase=phase)
        start = time()
        for i, case in enumerate(cases):
            result = self._assess_case(case)
            number_remaining = len(cases) - (i + 1)
            elapsed_secs = float(time() - start)
            secs_per_case = elapsed_secs / (i + 1)
            estimated_remaining_mins = int(10 * secs_per_case * number_remaining / 60) / 10
            if i % 100 == 99:
                self.logger.log(f'Completed case {i+1}/{len(cases)}. (Estimated minutes remaining: {estimated_remaining_mins})')
            if not result.significant:
                continue
            if phase == 1:
                results.append(result)
                log(result, ())
                continue
            possible_confounders = tuple_filter(
                lambda r0: SimpleConfounding(r0, result).probable_confounding(),
                previous_results,
            )
            if len(possible_confounders) == 0:
                results.append(result)
                log(result, possible_confounders)
        return tuple(results)

    def _get_cases(self, phase: int) -> tuple[Case, ...]:
        phenotypes = self._enumerate_phenotypes((1, 2))
        if phase == 1:
            return tuple_map(
                lambda c: Case(c[0], None, c[1], 'fractions'),
                product(phenotypes, combinations(self.cohorts, 2))
            )
        if phase == 2:
            return tuple_map(
                lambda c: Case(c[0], c[1], c[2], 'fractions'),
                filter(
                    lambda c: c[0] != c[1],
                    product(phenotypes, phenotypes, combinations(self.cohorts, 2))
                )
            )
        if phase == 3:
            return tuple_map(
                lambda c: Case(c[0], c[1], c[2], 'proximity'),
                product(phenotypes, phenotypes, combinations(self.cohorts, 2)),
            )
        raise ValueError(f'Phase requested: {phase}')

    def _enumerate_phenotypes(self, orders: tuple[int, ...]) -> tuple[PhenotypeCriteria, ...]:
        return StudyAutoAssessor._enumerate_phenotypes_from(self.channels, orders)

    @classmethod
    def _enumerate_phenotypes_from(cls, all_channels: tuple[str, ...], orders: tuple[int, ...]) -> tuple[PhenotypeCriteria, ...]:
        """
        Lists all combination phenotypes involving known channels in which
        the number of channels/markers involved in a given phenotype (whether
        positively or negatively), i.e. the "order" of the phenotype, is
        constrained to one of the specified orders.
        """
        # distribute = cls._distribute_markers_all_positive
        distribute = cls._distribute_markers_all_ways
        combos = chain(*list(map(
            distribute,
            chain(*map(
                lambda order: combinations(all_channels, order),
                orders,
            )),
        )))
        return tuple(combos)

    @classmethod
    def _distribute_markers_all_ways(cls, channels: tuple[str, ...]) -> list[PhenotypeCriteria]:
        """
        Forms positive/negative criteria phenotypes in all ways using all
        of the given channels/markers.
        """
        phenotypes: list[PhenotypeCriteria] = list()
        for subset in powerset(channels):
            if len(subset) == 0:
                continue
            complement = tuple(set(channels).difference(subset))
            c = PhenotypeCriteria(positive_markers=subset, negative_markers=complement)
            if len(channels) == 1:
                c = cls._reverse_polarity_special_cases(c)
            phenotypes.append(c)
        return phenotypes

    @classmethod
    def _distribute_markers_all_positive(cls, channels: tuple[str, ...]) -> list[PhenotypeCriteria]:
        return [PhenotypeCriteria(positive_markers=channels, negative_markers=())]

    @classmethod
    def _reverse_polarity_special_cases(cls, c: PhenotypeCriteria) -> PhenotypeCriteria:
        """
        Special treatment is given to the "distance dichotomized" virtual
        features, to emphasize the case of low value (closer distance) rather
        than high, which would normally be the important state for a marker feature.
        """
        p = list(c.positive_markers)
        n = list(c.negative_markers)
        specials = list(filter(lambda m: re.search('distance', m), p))
        p2 = tuple(set(p).difference(set(specials)))
        n2 = tuple(set(n).union(set(specials)))
        return PhenotypeCriteria(positive_markers=p2, negative_markers=n2)

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
        null = form_result(case, case.cohorts[0], ResultSignificance(1.0, 0, 0), False)
        if df.shape[0] == 0 or feature_name not in df.columns:
            return null
        cohorts = case.cohorts
        d1 = df[df['cohort'] == cohorts[0]]
        d2 = df[df['cohort'] == cohorts[1]]
        if d1.shape[0] == 0 or d2.shape[0] == 0:
            return null
        values1 = cast(Series, d1[feature_name])
        values2 = cast(Series, d2[feature_name])
        compare_result = compare(values1, values2)
        p = compare_result.pvalue
        effect = compare_result.effect
        higher_cohort = cohorts[1]
        if effect < 1.0:
            higher_cohort = cohorts[0]
            if effect != 0:
                effect = 1.0 / effect
        N = self.number_samples
        significance = ResultSignificance(float(p), effect, compare_result.fraction_data_used(N))
        return form_result(
            case,
            higher_cohort,
            significance,
            self.limits[feature_name].acceptable(significance),
        ) 

    def _form_results_dataframe(self, s1: tuple[Result, ...], s2: tuple[Result, ...], s3: tuple[Result, ...]):
        df1 = DataFrame([self._form_result_record(r) for r in s1])
        df1['metric'] = 'fraction'
        df2 = DataFrame([self._form_result_record(r) for r in s2])
        df2['metric'] = 'ratio'
        df3 = DataFrame([self._form_result_record(r) for r in s3])
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
    """
    Produces a sentential representation of a result in the context
    of a given study with its selected cohorts.
    """
    cohort_details: dict[str, ReportableCohort]
    study_name: str

    def __init__(self, cohort_details: dict[str, ReportableCohort], study_name: str):
        self.cohort_details = cohort_details
        self.study_name = study_name

    def augment(self, result: Result) -> ReportableResult:
        return self._form_reportable_result(result, self._generate_statement(result))

    def _generate_statement(self, result: Result) -> str:
        cohorts = self._reportable_cohorts(result)
        case = form_reportable_case(result.case)
        effect = AssessmentLogger._format_effect_no_times(result.significance.effect)
        p = AssessmentLogger._format_p(result.significance.p)
        if result.case.metric == 'fractions':
            if result.case.other is None:
                return fr'The overall fraction of {case.phenotype_str} cells is elevated by {effect} times in \textbf{{{cohorts.higher_cohort.abbreviation}}} samples compared with \textbf{{{cohorts.lower_cohort.abbreviation}}} samples, the difference being significant at level ${p}$ by the t-test.'
            else:
                return fr'The ratio of {case.phenotype_str} cells to {case.other_phenotype_str} cells is elevated by {effect} times in \textbf{{{cohorts.higher_cohort.abbreviation}}} samples compared with \textbf{{{cohorts.lower_cohort.abbreviation}}} samples, the difference being significant at level ${p}$ by the t-test.'
        if result.case.metric == 'proximity':
            return fr'The average number of {case.other_phenotype_str} cells within 100px of a given {case.phenotype_str} cell is {effect} times higher in \textbf{{{cohorts.higher_cohort.abbreviation}}} samples compared with \textbf{{{cohorts.lower_cohort.abbreviation}}} samples, the difference being significant at level ${p}$ by the t-test.'
        raise ValueError('This case is not covered for verbalization.')

    def _reportable_cohorts(self, result: Result) -> ReportableCohorts:
        return ReportableCohorts(
            self.cohort_details[result.higher_cohort],
            self.cohort_details[result.lower_cohort],
        )

    def _form_reportable_result(self, result: Result, statement: str) -> ReportableResult:
        metric = result.case.metric
        if metric == 'fractions' and result.case.other is not None:
            metric = 'ratios'
        return ReportableResult(
            result,
            form_reportable_case(result.case),
            self._reportable_cohorts(result),
            statement,
            metric,
            form_url(result, self.study_name),
            result.significance.quality(),
        )


class HighlightExtractor:
    """
    Extracts presentable "top results" by selecting only one from among
    any group in which a putative pattern appears.
    """

    @classmethod
    def extract_highlights(cls, results: FilteredResults, metadata: ReportStudyMetadata) -> Highlights:
        extracted: list[tuple[Result, ...]] = []
        by_metric: list[tuple[Result, ...]] = []
        for results_metric in (results.single_fractions, results.ratios, results.proximity):
            results25 = cls._get_top(25, results_metric)
            pared = cls._remove_common_patterns(results25)
            extracted.append(pared)
            by_metric.append(cls._get_top(25, pared))
        top3 = cls._get_top(3, tuple(chain(*extracted)))
        by_metric = list(map(lambda t: cls._remove_specific_set(top3, t), extracted))
        by_metric = list(map(lambda t: cls._get_top(5, t), by_metric))
        a = StatementAugmentor(metadata.cohorts_by_key, metadata.study_description_phrase)
        f = a.augment
        reportables = cast(
            tuple[tuple[ReportableResult, ...], tuple[ReportableResult, ...], tuple[ReportableResult, ...]],
            tuple_map(lambda t: tuple_map(lambda r: f(r), t), by_metric),
        )
        highlights = Highlights(tuple_map(lambda r: f(r), top3), *reportables, results.dataframe.shape[0])
        return highlights

    @classmethod
    def _remove_specific_set(cls, specific: tuple[Result, ...], t: tuple[Result, ...]) -> tuple[Result, ...]:
        def compare(r1: Result, r2: Result) -> bool:
            return r1.case == r2.case
        return tuple_filter(lambda r: not any(map(lambda s: compare(s, r), specific)) , t)

    @classmethod
    def _get_top(cls, number: int, results: tuple[Result, ...]) -> tuple[Result, ...]:
        sorted_results = sorted(list(results), key=lambda r: -1 * r.quality())
        return tuple(sorted_results[0:number])

    @classmethod
    def _find_co_occurring(cls, positively: bool, p: PhenotypeCriteria, results: tuple[Result, ...]) -> tuple[bool, ...]:
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
    def _remove_common_patterns(cls, results: tuple[Result, ...]) -> tuple[Result, ...]:
        """
        For each phenotype, decide if the phenotype occurs frequently
        enough in the result set (with the same "sign" of influence) to constitute
        a pattern. Patterns of results are replaced by one representative, the
        member with the highest quality score.
        """
        phenotypes_occurring = cast(list[PhenotypeCriteria], list(
            set(map(lambda r: r.case.phenotype, results)).union(set(map(lambda r: r.case.other, results))).difference(set([None])))
        )
        representatives = []
        pattern_membership = [False for _ in results]
        for p in phenotypes_occurring:
            positively_occurring = cls._find_co_occurring(True, p, results)
            negatively_occurring = cls._find_co_occurring(False, p, results)
            results_p = tuple_map(lambda pair: pair[1], filter(lambda pair: pair[0], zip(positively_occurring, results)))
            results_n = tuple_map(lambda pair: pair[1], filter(lambda pair: pair[0], zip(negatively_occurring, results)))
            if len(results_p) > 2:
                representative = cls._get_top(1, results_p)[0]
                if representative not in representatives:
                    representatives.append(representative)
                pattern_membership = [m1 or m2 for m1, m2 in zip(pattern_membership, positively_occurring)]
            if len(results_n) > 2:
                representative = cls._get_top(1, results_n)[0]
                if representative not in representatives:
                    representatives.append(representative)
                pattern_membership = [m1 or m2 for m1, m2 in zip(pattern_membership, negatively_occurring)]
        results_no_pattern = list(map(lambda pair: pair[1], filter(lambda pair: not pair[0], zip(pattern_membership, results))))
        return tuple(representatives + results_no_pattern)


class CohortSummarizer:
    """
    Text processing to come up with a reasonable abbreviation
    for each cohort definition.
    """
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
    """
    Extracts study metadata for the presentation/report layer.
    """

    @classmethod
    def form_presentation_extracts(cls, access: StudyDataAccessor, omitted_cohorts: tuple[str, ...]) -> ReportStudyMetadata:
        summary = access._retrieve_study_summary()
        s = CohortSummarizer(
            list(filter(lambda c: c.identifier not in omitted_cohorts, summary.cohorts.cohorts)),
            summary.cohorts.assignments,
        )
        cohorts = s.get_cohorts()
        cohorts_by_key = s.get_cohorts_by_key()
        author = cls._extract_surname(summary.products.publication.first_author_name)
        versions = access._retrieve_software_versions()
        library_versions = ' '.join(map(lambda v: f'{v.component_name} v{v.version}', versions))
        return ReportStudyMetadata(
            access.get_study_name(),
            cohorts,
            len(cohorts),
            sum(map(lambda c: c.number_samples, cohorts)),
            author,
            cls._form_reference(summary.products.publication, author),
            summary.context.assay.name.lower(),
            summary.counts.channels,
            cohorts_by_key,
            library_versions,
            summary.products.data_release.url,
        )

    @classmethod
    def _form_reference(cls, p: Publication, author: str) -> str:
        return f'{author} et al. \\href{{{p.url}}}{{{p.title}}} ({p.date})'

    @classmethod
    def _extract_surname(cls, author: str) -> str:
        if ',' in author:
            return author.split(',')[0].rstrip()
        return author.split(' ')[-1]



