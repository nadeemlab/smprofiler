"""Data analysis script with automated multi-feature assessments."""
import re
from typing import cast
from typing import Callable
from itertools import product
from itertools import combinations
from itertools import chain

from pandas import concat
from pandas import DataFrame
from pandas import Series
from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.http_data_accessor import StudyDataAccessor
from smprofiler.db.http_data_accessor import univariate_pair_compare as compare
from smprofiler.standalone_utilities.log_formats import colorized_logger

from smprofiler.workflow.automated_analysis.types import Case
from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.types import ResultSignificance
from smprofiler.workflow.automated_analysis.types import Limits
from smprofiler.workflow.automated_analysis.types import DEFAULT_LIMITS
from smprofiler.workflow.automated_analysis.types import LIMITS_SEVERE
from smprofiler.workflow.automated_analysis.types import FilteredResults
from smprofiler.workflow.automated_analysis.types import Highlights
from smprofiler.workflow.automated_analysis.confounding import SimpleConfounding
from smprofiler.workflow.automated_analysis.assessment_logger import AssessmentLogger

logger = colorized_logger(__name__)

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

    def __init__(self, access: StudyDataAccessor, interactive: bool, limits: Limits=DEFAULT_LIMITS):
        self.access = access
        self.limits = limits
        self.logger = AssessmentLogger(interactive=interactive)
        self.add_subresource(self.access)
        self.add_subresource(self.logger)

    def get_filtered_results(self) -> tuple[FilteredResults, Highlights]:
        self._initial_fetch()
        singleton_significants = self._get_results_from_phase(1, ())
        ratio_significants = self._get_results_from_phase(2, singleton_significants)
        proximity_significants = self._get_results_from_phase(3, singleton_significants)
        args = (singleton_significants, ratio_significants, proximity_significants)
        results = FilteredResults(*args, self._form_dataframe(*args))
        highlights = HighlightExtractor.extract_highlights(results)
        return (results, highlights)

    def _form_dataframe(self, s1: tuple[Result, ...], s2: tuple[Result, ...], s3: tuple[Result, ...]):
        df1 = DataFrame([self._form_record(r) for r in s1])
        df1['metric'] = 'fraction'
        df2 = DataFrame([self._form_record(r) for r in s2])
        df2['metric'] = 'ratio'
        df3 = DataFrame([self._form_record(r) for r in s3 if LIMITS_SEVERE.acceptable(r.significance)])
        df3['metric'] = 'proximity'
        df = concat([df1, df2, df3], axis=0)
        return df

    def _form_record(self, r: Result) -> dict[str, str | float | int]:
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

    def _get_results_from_phase(self, phase: int, previous_results: tuple[Result, ...]):
        results: list[Result] = []
        log = self._get_logging(phase)
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

    def _get_logging(self, phase: int) -> Callable[[Result, tuple[Result, ...]], None]:
        if phase == 1:
            return self.logger.log_singleton
        if phase == 2:
            return self.logger.log_ratios
        if phase == 3:
            return self.logger.log_proximity
        raise ValueError('Logging only available for known analysis phases.')

    def _get_cases(self, phase: int) -> tuple[Case, ...]:
        if phase == 1:
            return tuple(map(
                lambda c: Case(self._form_single_phenotype(c[0]), None, c[1], 'fractions'),
                product(self.channels, combinations(self.cohorts, 2))
            ))
        if phase == 2:
            return tuple(map(
                lambda c: Case(self._form_single_phenotype(c[0]), self._form_single_phenotype(c[1]), c[2], 'fractions'),
                filter(
                    lambda c: c[0] != c[1],
                    product(self.channels, self.channels, combinations(self.cohorts, 2))
                )
            ))
        if phase == 3:
            return tuple(map(
                lambda c: Case(self._form_single_phenotype(c[0]), self._form_single_phenotype(c[1]), c[2], 'proximity'),
                product(self.channels, self.channels, combinations(self.cohorts, 2)),
            ))
        raise ValueError(f'Phase requested: {phase}')

    def _initial_fetch(self) -> None:
        self.channels = tuple(self.access._retrieve_feature_names())
        self.cohorts = tuple(sorted(list(set(self.access._retrieve_cohorts()['cohort'])), key=lambda x: int(x)))
        self.logger.set_name_width(max(map(len, self.channels)))
        self._log(f'Using channels: {self.channels}')
        self._log(f'Using cohorts: {self.cohorts}')

    def _form_single_phenotype(self, channel: str) -> PhenotypeCriteria:
        if re.search('distance', channel):
            return PhenotypeCriteria(positive_markers=(), negative_markers=(channel,))
        return PhenotypeCriteria(positive_markers=(channel,), negative_markers=())

    def _assess_case(self, case: Case) -> Result:
        handlers = {
            'fractions': self._assess_fraction,
            'proximity': self._assess_proximity,
        }
        return handlers[case.metric](case)

    def _get_phenotypes(self, case: Case) -> tuple[PhenotypeCriteria, ...]:
        return cast(tuple[PhenotypeCriteria, ...], tuple(
            filter(
                lambda p0: p0 is not None,
                [case.phenotype, case.other]
            )
        ))

    def _assess_fraction(self, case: Case) -> Result:
        df = self.access.fractions(self._get_phenotypes(case))
        return self._assess_case_df(df, case, 'fraction')

    def _assess_proximity(self, case: Case) -> Result:
        df = self.access.two_phenotype_spatial_metric(
            'proximity',
            self._get_phenotypes(case),
            'proximity',
        )
        return self._assess_case_df(df, case, 'proximity')

    def _assess_case_df(self, df: DataFrame, case: Case, feature_name: str) -> Result:
        cohorts = case.cohorts
        values1 = cast(Series, df[df['cohort'] == cohorts[0]][feature_name])
        values2 = cast(Series, df[df['cohort'] == cohorts[1]][feature_name])
        p, effect = compare(values1, values2)
        higher_cohort = cohorts[1]
        if effect < 1.0:
            higher_cohort = cohorts[0]
            effect = 1.0 / effect
        significance = ResultSignificance(float(p), effect)
        return Result(case, higher_cohort, significance, self.limits.acceptable(significance))

    def _log(self, *args, **kwargs) -> None:
        self.logger.log(*args, **kwargs)


class HighlightExtractor:
    @classmethod
    def extract_highlights(cls, results: FilteredResults) -> Highlights:
        extracted: list[tuple[Result, ...]] = []
        for results_metric in (results.single_fractions, results.ratios, results.proximity):
            results20 = cls.get_top(20, results_metric)
            pared = cls.remove_common_patterns(results20)
            extracted.append(pared)
        top3 = cls.get_top(3, tuple(chain(*extracted)))
        return Highlights(top3, FilteredResults(*extracted, None))

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
        return tuple(map(occurring, results))

    @classmethod
    def remove_common_patterns(cls, results: tuple[Result, ...]) -> tuple[Result, ...]:
        phenotypes_occurring = cast(list[PhenotypeCriteria], list(set(map(lambda r: r.case.phenotype, results)).union(set(map(lambda r: r.case.other, results))).difference(set([None]))))
        representatives = []
        pattern_membership = [False for _ in results]
        for p in phenotypes_occurring:
            positively_occurring = cls.find_co_occurring(True, p, results)
            negatively_occurring = cls.find_co_occurring(False, p, results)
            results_p = tuple(map(lambda pair: pair[1], filter(lambda pair: pair[0], zip(positively_occurring, results))))
            results_n = tuple(map(lambda pair: pair[1], filter(lambda pair: pair[0], zip(negatively_occurring, results))))
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


