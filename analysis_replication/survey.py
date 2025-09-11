"""Data analysis script with automated multi-feature assessments."""
import sys
import re
from decimal import Decimal
from typing import cast
from typing import Literal
from itertools import product
from itertools import combinations
from os.path import exists

from pandas import concat
from pandas import DataFrame
from attrs import define
from attrs import field
from numpy import matrix
from numpy import array
from numpy.linalg import inv
from numpy import matmul

from smprofiler.standalone_utilities.terminal_scrolling import TerminalScrollingBuffer
from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.http_data_accessor import StudyDataAccessor
from smprofiler.db.http_data_accessor import univariate_pair_compare as compare
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

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

class SimpleConfounding:
    """
    Estimate whether ratios result (result2) may be confounded by singleton result
    (result1). This can happen when:
      - either the numerator or denominator phenotype in result2 is the singleton
        phenotype of result1
      - either of the two phenotypes for proximity in result2 is the singleton
        phenotype of result1,
    and the direction of association implied by both results is the same.
    """
    r1: Result
    r2: Result

    def __init__(self, result1: Result, result2: Result):
        self.r1 = result1
        self.r2 = result2

    def probable_confounding(self) -> bool:
        return self._check_result_types() and (
            (not self._incomparable_due_to_cohort_set()) and
            (self._get_common_phenotype() is not None) and
            self._direction_of_association_consistent()
        )

    def _check_result_types(self) -> bool:
        c1 = self.r1.case
        c2 = self.r2.case
        return (
            c1.metric == 'fractions' and
            c2.metric == 'fractions' and
            c1.other is None and
            c2.other is not None
        ) or (
            c1.metric == 'fractions' and
            c2.metric == 'proximity' and
            c1.other is None
        )

    def _incomparable_due_to_cohort_set(self) -> bool:
        c1 = self.r1.case
        c2 = self.r2.case
        return set(c1.cohorts) != set(c2.cohorts)

    def _get_common_phenotype(self) -> Literal['phenotype', 'other', None]:
        c1 = self.r1.case
        c2 = self.r2.case
        if c1.phenotype == c2.phenotype:
            return 'phenotype'
        if c1.phenotype == c2.other:
            return 'other'
        return None

    def _direction_of_association_consistent(self) -> bool:
        common = self._get_common_phenotype()
        if self.r2.case.metric == 'fractions':
            if common == 'phenotype':
                return self.r1.higher_cohort == self.r2.higher_cohort
            if common == 'other':
                return self.r1.higher_cohort != self.r2.higher_cohort
        if self.r2.case.metric == 'proximity':
            return self.r1.higher_cohort == self.r2.higher_cohort
        return False

DEFAULT_LIMITS = Limits(1.3, 0.01, 0.2, 2.0)

@define
class FilteredResults:
    single_fractions: tuple[Result, ...]
    ratios: tuple[Result, ...]
    proximity: tuple[Result, ...]

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

    def get_filtered_results(self) -> FilteredResults:
        self._initial_fetch()
        singleton_significants: list[Result] = []
        for case in self._get_cases(phase=1):
            result = self._assess_case(case)
            if result.significant:
                singleton_significants.append(result)
                self.logger.log_singleton(result)
        ratio_significants: list[Result] = []
        for case in self._get_cases(phase=2):
            result = self._assess_case(case)
            if result.significant:
                confounding = tuple(filter(
                    lambda r0: SimpleConfounding(r0, result).probable_confounding(),
                    singleton_significants,
                ))
                if len(confounding) == 0:
                    ratio_significants.append(result)
                self.logger.log_ratios(result, confounding = confounding)
        proximity_significants: list[Result] = []
        for case in self._get_cases(phase=3):
            result = self._assess_case(case)
            if result.significant:
                confounding = tuple(filter(
                    lambda r0: SimpleConfounding(r0, result).probable_confounding(),
                    singleton_significants,
                ))
                if len(confounding) == 0:
                    proximity_significants.append(result)
                self.logger.log_proximity(result, confounding = confounding)
        return FilteredResults(tuple(singleton_significants), tuple(ratio_significants), tuple(proximity_significants))

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
        handlers = (
            ('fractions', self._assess_fraction),
            ('proximity', self._assess_proximity),
        )
        for metric, handler in handlers:
            if case.metric == metric:
                return handler(case)
        raise ValueError

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
        values1 = df[df['cohort'] == cohorts[0]][feature_name]
        values2 = df[df['cohort'] == cohorts[1]][feature_name]
        p, effect = compare(values1, values2)
        higher_cohort = cohorts[1]
        if effect < 1.0:
            higher_cohort = cohorts[0]
            effect = 1.0 / effect
        significance = ResultSignificance(float(p), effect)
        return Result(case, higher_cohort, significance, self.limits.acceptable(significance))

    def _log(self, *args, **kwargs) -> None:
        self.logger.log(*args, **kwargs)

class AssessmentLogger(ChainableDestructableResource):
    interactive: bool
    buffer: TerminalScrollingBuffer
    name_width: int

    def __init__(self, interactive: bool=True, scrolling_buffer_lines: int=20):
        self.interactive = interactive
        if interactive:
            self.buffer = TerminalScrollingBuffer(scrolling_buffer_lines)
            self.add_subresource(self.buffer)

    def set_name_width(self, w: int) -> None:
        self.name_width = w

    def log(self, message: str, **kwargs) -> None:
        if self.interactive:
            self.buffer.add_line(message, **kwargs)
        else:
            logger.info(message)

    def log_singleton(self, result: Result) -> None:
        message = self._format_singleton(result)
        self.log(f'Hit: {message}', sticky_header='Single channel assessment phase')

    def log_ratios(self, result: Result, confounding: tuple[Result, ...]):
        qualification = self._form_qualification(confounding)
        message = self._format_ratio(result)
        message = f'Hit: {message}   {qualification}'
        self.log(message, sticky_header='Channel ratios assessment phase')

    def log_proximity(self, result: Result, confounding: tuple[Result, ...]):
        qualification = self._form_qualification(confounding)
        message = self._format_proximity(result)
        message = f'Hit: {message}   {qualification}'
        self.log(message, sticky_header='Proximity assessment phase')

    def _form_qualification(self, confounding: tuple[Result, ...]) -> str:
        if len(confounding) > 0:
            strings = map(lambda r0: self._format_phenotype(r0.case.phenotype), confounding)
            reference = ', '.join(strings)
            qualification = f'(Probable confounding with {reference} results)'
        else:
            qualification = ''
        return qualification

    def _format_singleton(self, result: Result) -> str:
        s = result.significance
        w = self.name_width + 22
        p = self._format_phenotype((result.case.phenotype))
        pre = ('{:>' + str(w) + '}').format(f'{p} fractions in cohort {result.higher_cohort} (vs {result.lower_cohort()})')
        message = f'{pre} {self._format_effect(s.effect)}   {self._format_p(s.p)}'
        return message

    def _format_effect(self, e: float) -> str:
        return '{:>12}'.format('%.4f' % e) + ' x'

    def _format_p(self, p: float) -> str:
        return '{:>12}'.format('p = ' + '%.5f' % p if p >= 0.0001 else '{:.2E}'.format(Decimal(p)))

    def _format_phenotype(self, p: PhenotypeCriteria) -> str:
        return ' '.join([x + '+' for x in p.positive_markers]) + ' '.join([x + '-' for x in p.negative_markers])

    def _format_ratio(self, result: Result) -> str:
        if result.case.other is None:
            raise ValueError('Only use this function for ratio features.')
        s = result.significance
        p1 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.phenotype))
        p2 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.other))
        pre = f'{p1} / {p2}   ratios in cohort {result.higher_cohort} (vs {result.lower_cohort()})'
        return f'{pre} {self._format_effect(s.effect)}   {self._format_p(s.p)}'

    def _format_proximity(self, result: Result) -> str:
        if result.case.other is None:
            raise ValueError('Proximity requires two phenotypes.')
        s = result.significance
        p1 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.phenotype))
        p2 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.other))
        pre = f'{p1} have a number of nearby {p2}   cells in cohort {result.higher_cohort} (vs {result.lower_cohort()})'
        return f'{pre} {self._format_effect(s.effect)}   {self._format_p(s.p)}'


def survey(host: str, study: str, interactive: bool) -> DataFrame:
    with StudyAutoAssessor(StudyDataAccessor(study, host=host), interactive=interactive) as a:
        results = a.get_filtered_results()
        singleton_significants = results.single_fractions
        ratio_significants = results.ratios
        proximity_significants = results.proximity

    print('')
    print('Single channel fractions results:')
    for result in sorted(singleton_significants, key=lambda r: int(r.higher_cohort)):
        print(a.logger._format_singleton(result))
    print('')
    print('Ratio of channels fractions results:')
    def c(p: PhenotypeCriteria | None) -> PhenotypeCriteria:
        return cast(PhenotypeCriteria, p)
    for result in sorted(ratio_significants, key=lambda r: (int(r.higher_cohort), a.logger._format_phenotype(c(r.case.other)), a.logger._format_phenotype(r.case.phenotype))):
        print(a.logger._format_ratio(result))
    print('')

    severe = Limits(1.5, 0.005, 0.2, 3.0)

    print('Proximity results:')
    for result in sorted(proximity_significants, key=lambda r: (int(r.higher_cohort), a.logger._format_phenotype(c(r.case.other)), a.logger._format_phenotype(r.case.phenotype))):
        if severe.acceptable(result.significance):
            print(a.logger._format_proximity(result))

    def _form_record(r: Result) -> dict[str, str | float | int]:
        return {
            'multiplier': r.significance.effect,
            'p': r.significance.p,
            'higher_cohort': r.higher_cohort,
            'c1': r.case.cohorts[0],
            'c2': r.case.cohorts[1],
            'p1': a.logger._format_phenotype(r.case.phenotype),
            'p2': a.logger._format_phenotype(r.case.other) if r.case.other else '',
        }

    df1 = DataFrame([_form_record(r) for r in singleton_significants])
    df1['metric'] = 'fraction'
    df2 = DataFrame([_form_record(r) for r in ratio_significants])
    df2['metric'] = 'ratio'
    df3 = DataFrame([_form_record(r) for r in proximity_significants if severe.acceptable(r.significance)])
    df3['metric'] = 'proximity'
    return concat([df1, df2, df3], axis=0)


def get_default_host(given: str | None) -> str | None:
    if given is not None:
        return given
    filename = 'api_host.txt'
    if exists(filename):
        with open(filename, 'rt', encoding='utf-8') as file:
            host = file.read().rstrip()
    else:
        host = None
    return host

if __name__=='__main__':
    if len(sys.argv) == 2:
        study = sys.argv[1]
    else:
        raise ValueError('Supply a study name.')
    host = get_default_host(None)
    if host is None:
        raise RuntimeError('Could not determine API server hostname.')
    df = survey(host, study, True)

