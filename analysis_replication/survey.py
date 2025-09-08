"""Data analysis script for one dataset."""
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
from smprofiler.standalone_utilities.resource_chainable import ChainableDestructableResource

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.http_data_accessor import DataAccessor
from smprofiler.db.http_data_accessor import univariate_pair_compare as compare
from smprofiler.db.http_data_accessor import get_fractions

Metric = Literal['fractions', 'proximity']

@define
class Case:
    """
    In this context, that of a single-study survey, a single "case" means
    comparison of one or two phenotypes (cell sets) along two given sample cohorts,
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

class Confounding:
    @classmethod
    def probable_confounding(cls, result1: Result, result2: Result) -> bool:
        """
        Estimate whether ratios result (result2) may be confounded by singleton result (result1).
        This can happen when either the numerator or denominator phenotype in result2 is the
        singleton result of result1, and the direction of association implied by both results is the same.
        """
        r1 = result1
        r2 = result2
        if cls._incomparable_results(r1, r2):
            return False
        if cls._get_common_phenotype(r1, r2) is None:
            return False
        return cls._direction_of_association_consistent(r1, r2)

    @classmethod
    def _incomparable_results(cls, r1: Result, r2: Result) -> bool:
        return set(r1.case.cohorts) != set(r2.case.cohorts)

    @classmethod
    def _get_common_phenotype(cls, r1: Result, r2: Result) -> Literal['phenotype', 'other', None]:
        if r1.case.phenotype == r2.case.phenotype:
            return 'phenotype'
        if r1.case.phenotype == r2.case.other:
            return 'other'
        return None

    @classmethod
    def _direction_of_association_consistent(cls, r1: Result, r2: Result) -> bool:
        common = cls._get_common_phenotype(r1, r2)
        if common == 'phenotype':
            return r1.higher_cohort == r2.higher_cohort
        if common == 'other':
            return r1.higher_cohort != r2.higher_cohort
        return False

DEFAULT_LIMITS = Limits(1.3, 0.01, 0.2, 2.0)

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


class AutoAssessor(ChainableDestructableResource):
    """
    Automatically search and filter significant results from among, first, elementary
    results involving one phenotype, then incrementally increase the complexity of the
    metrics in the search space, while filtering out additional results which are
    probably confounded by previous ones.
    This uses default limits that trade-off a significance measure and effect size.
    """
    access: DataAccessor
    limits: Limits

    def __init__(self, access: DataAccessor, limits: Limits=DEFAULT_LIMITS):
        self.access = access
        self.limits = limits

    def get_subresources(self) -> tuple[DataAccessor,]:
        return (self.access,)

    def assess(self, case: Case) -> Result:
        if case.metric == 'fractions':
            return self._assess_fraction(case)
        if case.metric == 'proximity':
            return self._assess_proximity(case)
        raise ValueError

    def _pad_channel_lists(self, p: PhenotypeCriteria) -> PhenotypeCriteria:
        m1 = ('',) if len(p.positive_markers) == 0 else p.positive_markers
        m2 = ('',) if len(p.negative_markers) == 0 else p.negative_markers       
        return PhenotypeCriteria(positive_markers=m1, negative_markers=m2)

    def _assess_fraction(self, case: Case) -> Result:
        df = self.access.counts(
            tuple(map(lambda p: self._pad_channel_lists(cast(PhenotypeCriteria, p)), filter(lambda p0: p0 is not None, [case.phenotype, case.other])))
        )
        return self._assess_df(df, case)

    def _assess_proximity(self, case: Case) -> Result:
        df = self.access._two_phenotype_spatial_metric(
            'proximity',
            tuple(map(lambda p: self._pad_channel_lists(cast(PhenotypeCriteria, p)), filter(lambda p0: p0 is not None, [case.phenotype, case.other]))),
        )
        return self._assess_df(df, case)

    def _assess_df(self, df: DataFrame, case: Case) -> Result:
        df = df.loc[:,~df.columns.duplicated()].copy()
        if len(df.columns) == 3:
            p1 = df.columns[2]
            p2 = df.columns[2]
        elif re.search(' and ', df.columns[2]):
            p1 = df.columns[3]
            p2 = df.columns[4]
        else:
            p1 = df.columns[2]
            p2 = df.columns[3]
        if p1 == p2:
            p2 = 'all cells'
        cohorts = case.cohorts
        fractions1, fractions2 = get_fractions(df, p1, p2, *cohorts, omit_zeros=True)
        p, effect = compare(fractions1, fractions2)
        higher_cohort = case.cohorts[1]
        if effect < 1.0:
            cohorts = cast(tuple[str, str], tuple(list(reversed(case.cohorts))))
            fractions1, fractions2 = get_fractions(df, p1, p2, *cohorts, omit_zeros=True)
            p, effect = compare(fractions1, fractions2)
            higher_cohort = cohorts[1]
        significance = ResultSignificance(float(p), effect)
        if effect < 1.0:
            return Result(case, None, significance, False)
        return Result(case, higher_cohort, significance, self.limits.acceptable(significance))

def _format_effect(e: float) -> str:
    return '{:>12}'.format('%.4f' % e) + ' x'

def _format_p(p: float) -> str:
    return '{:>12}'.format('p = ' + '%.5f' % p if p >= 0.0001 else '{:.2E}'.format(Decimal(p)))

def survey(host: str, study: str) -> DataFrame:
    with AutoAssessor(DataAccessor(study, host=host)) as a:
        b = TerminalScrollingBuffer(20)
        channels = a.access._retrieve_feature_names()
        # if study == '...':
        #     channels = list(filter(lambda s: len(s) < 6, channels))
        #     # channels = list(filter(lambda s: len(s) >= 6, channels))
        cohorts = sorted(list(set(a.access._retrieve_cohorts()['cohort'])), key=lambda x: int(x))
        m = max(map(len, channels))
        b.add_line(f'Using channels: {channels}')
        b.add_line(f'Using cohorts: {cohorts}')

        def _format_phenotype(p: Phenotype) -> str:
            return ' '.join([m + '+' for m in p.positive_markers]) + ' '.join([m + '-' for m in p.negative_markers])

        def _format_singleton(result: Result) -> str:
            s = result.significance
            w = m + 22
            pre = ('{:>' + str(w) + '}').format(f'{_format_phenotype(result.case.phenotype)} fractions in cohort {result.higher_cohort} (vs {result.lower_cohort()})')
            message = f'{pre} {_format_effect(s.effect)}   {_format_p(s.p)}'
            return message

        def _form_single_phenotype(channel: str) -> Phenotype:
            if re.search('distance', channel):
                return Phenotype([], [channel])
            return Phenotype([channel], [])

        singleton_significants: list[Result] = []
        for channel, (c1, c2) in product(channels, combinations(cohorts, 2)):
            p1 = _form_single_phenotype(channel)
            p2 = None
            case = Case(p1, p2, (c1, c2), 'fractions')
            result = a.assess(case)
            if result.significant:
                message = _format_singleton(result)
                b.add_line(f'Hit: {message}', sticky_header='Single channel assessment phase')
                if result.significant:
                    singleton_significants.append(result)

        def _format_ratio(r: Result) -> str:
            s = result.significance
            p1 = ('{:>' + str(m + 1) + '}').format(_format_phenotype(result.case.phenotype))
            p2 = ('{:>' + str(m + 1) + '}').format(_format_phenotype(result.case.other))
            pre = f'{p1} / {p2}   ratios in cohort {result.higher_cohort} (vs {result.lower_cohort()})'
            return f'{pre} {_format_effect(s.effect)}   {_format_p(s.p)}'

        ratio_significants: list[Result] = []
        for channel1, channel2, (c1, c2) in product(channels, channels, combinations(cohorts, 2)):
            if channel1 == channel2:
                continue
            p1 = _form_single_phenotype(channel1)
            p2 = _form_single_phenotype(channel2)
            case = Case(p1, p2, (c1, c2), 'fractions')
            result = a.assess(case)
            if result.significant:
                confounding = tuple(_format_phenotype(r0.case.phenotype) for r0 in singleton_significants if Confounding.probable_confounding(r0, result))
                if len(confounding) > 0:
                    l = ', '.join(confounding)
                    qualification = f'(Probable confounding with {l} results)'
                else:
                    qualification = ''
                    ratio_significants.append(result)
                message = _format_ratio(result)
                message = f'Hit: {message}   {qualification}'
                b.add_line(message, sticky_header='Channel ratios assessment phase')

        def _format_proximity(r: Result) -> str:
            s = result.significance
            p1 = ('{:>' + str(m + 1) + '}').format(_format_phenotype(result.case.phenotype))
            p2 = ('{:>' + str(m + 1) + '}').format(_format_phenotype(result.case.other))
            pre = f'{p1} have a number of nearby {p2}   cells in cohort {result.higher_cohort} (vs {result.lower_cohort()})'
            return f'{pre} {_format_effect(s.effect)}   {_format_p(s.p)}'

        proximity_significants: list[Result] = []
        for channel1, channel2, (c1, c2) in product(channels, channels, combinations(cohorts, 2)):
            p1 = _form_single_phenotype(channel1)
            p2 = _form_single_phenotype(channel2)
            case = Case(p1, p2, (c1, c2), 'proximity')
            result = a.assess(case)
            if result.significant:
                confounding = tuple(_format_phenotype(r0.case.phenotype) for r0 in singleton_significants if Confounding.probable_confounding(r0, result))
                if len(confounding) > 0:
                    number = ', '.join(confounding)
                    qualification = f'(Probable confounding with {number} results)'
                else:
                    qualification = ''
                    proximity_significants.append(result)
                message = _format_proximity(result)
                message = f'Hit: {message}   {qualification}'
                b.add_line(message, sticky_header='Proximity assessment phase')

        b.finish()

    print('')
    print('Single channel fractions results:')
    for result in sorted(singleton_significants, key=lambda r: int(r.higher_cohort)):
        print(_format_singleton(result))
    print('')
    print('Ratio of channels fractions results:')
    for result in sorted(ratio_significants, key=lambda r: (int(r.higher_cohort), _format_phenotype(r.case.other), _format_phenotype(r.case.phenotype))):
        print(_format_ratio(result))
    print('')

    severe = Limits(1.5, 0.005, 0.2, 3.0)

    print('Proximity results:')
    for result in sorted(proximity_significants, key=lambda r: (int(r.higher_cohort), _format_phenotype(r.case.other), _format_phenotype(r.case.phenotype))):
        if severe.acceptable(result.significance):
            print(_format_proximity(result))

    def _form_record(r: Result) -> dict[str, str | float | int]:
        return {
            'multiplier': r.significance.effect,
            'p': r.significance.p,
            'higher_cohort': r.higher_cohort,
            'c1': r.case.cohorts[0],
            'c2': r.case.cohorts[1],
            'p1': _format_phenotype(r.case.phenotype),
            'p2': _format_phenotype(r.case.other) if r.case.other else '',
        }

    df1 = DataFrame([_form_record(r) for r in singleton_significants])
    df1['metric'] = 'fraction'
    df2 = DataFrame([_form_record(r) for r in ratio_significants])
    df2['metric'] = 'ratio'
    df3 = DataFrame([_form_record(r) for r in proximity_significants if severe.acceptable(r.significance)])
    df3['metric'] = 'proximity'
    return concat([df1, df2, df3], axis=0)

if __name__=='__main__':
    if len(sys.argv) == 2:
        study = sys.argv[1]
    else:
        raise ValueError('Supply a study name.')
    host = get_default_host(None)
    if host is None:
        raise RuntimeError('Could not determine API server hostname.')
    df = survey(host, study)
