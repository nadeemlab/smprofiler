"""Convenience caller of HTTP methods for data access."""
import re
from itertools import chain
from urllib.parse import urlencode
from requests import get as get_request
from time import sleep
from time import time
from datetime import datetime
from os import environ as os_environ

from pandas import Series
from pandas import DataFrame
from pandas import concat
from numpy import inf
from numpy import nan
from numpy import isnan
from numpy import mean
from scipy.stats import ttest_ind
from attrs import define

from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.standalone_utilities.key_value_store import KeyValueStore
from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.exchange_data_formats.metrics import SoftwareComponentVersion
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCounts
from smprofiler.db.exchange_data_formats.metrics import UnivariateMetricsComputationResult
from smprofiler.db.exchange_data_formats.study import StudySummary


def sleep_poll():
    seconds = 10
    if 'SMPROFILER_FAST_POLLING' in os_environ:
        seconds = 1
    print(f'Waiting {seconds} seconds to poll.')
    sleep(seconds)


class StudyDataAccessor(ChainableDestructableResource):
    """
    Convenience caller of HTTP methods for data access (study metadata, computed metrics).
    """
    cache: KeyValueStore

    def __init__(self, study: str, host: str):
        self.cache = KeyValueStore()
        use_http = False
        if re.search('^http://', host):
            use_http = True
            host = re.sub(r'^http://', '', host)
        self.host = host
        self.study = study
        self.use_http = use_http
        self.cohorts = self._retrieve_cohorts()
        self.all_cells = self._retrieve_all_cells_counts()

    def get_subresources(self) -> tuple[KeyValueStore]:
        return (self.cache,)

    def fractions(self, phenotypes: tuple[PhenotypeCriteria, ...]):
        individual_counts_series = [
            self._get_counts_series(self._pad_channel_lists(p), f'p{i+1}')
            for i, p in enumerate(phenotypes)
        ]
        df = concat(
            [self.cohorts, self.all_cells, *individual_counts_series],
            axis=1,
        )
        df.replace([inf, -inf], nan, inplace=True)
        if len(phenotypes) == 1:
            return append_fractions_feature(df, 'p1', 'all cells', 'fraction')
        if len(phenotypes) == 2:
            return append_fractions_feature(df, 'p1', 'p2', 'fraction')
        raise ValueError('Fractions feature supported for one or two phenotypes.')

    def two_phenotype_spatial_metric(self, feature_class: str, criteria: tuple[PhenotypeCriteria, ...], feature_name: str):
        p1 = criteria[0]
        p2 = criteria[1]
        parts1 = self._form_query_parameters_key_values(p1)
        parts2 = self._form_query_parameters_key_values(p2, ordinality=2)
        parts = parts1 + parts2 + [('study', self.study), ('feature_class', feature_class)]
        if feature_class == 'co-occurrence':
            parts.append(('radius', '100'))
        if feature_class == 'proximity':
            parts.append(('radius', '100'))
        query = urlencode(parts)
        endpoint = 'request-spatial-metrics-computation-custom-phenotypes'
        return self._polling_retrieve_values(endpoint, query, feature_name)

    def get_study_name(self) -> str:
        return StudyCollectionNaming.strip_token(self.study)[0]

    def _pad_channel_lists(self, p: PhenotypeCriteria) -> PhenotypeCriteria:
        m1 = ('',) if len(p.positive_markers) == 0 else p.positive_markers
        m2 = ('',) if len(p.negative_markers) == 0 else p.negative_markers
        return PhenotypeCriteria(positive_markers=m1, negative_markers=m2)

    def _retrieve_cohorts(self) -> DataFrame:
        summary = self._retrieve_study_summary()
        return DataFrame([model.model_dump() for model in summary.cohorts.assignments]).set_index('sample')

    def _retrieve_study_summary(self) -> StudySummary:
        summary_obj, _ = self._retrieve('study-summary', urlencode([('study', self.study)]))
        return StudySummary.model_validate(summary_obj)
 
    def _retrieve_feature_names(self) -> list[str]:
        names_obj, _ = self._retrieve('cell-data-binary-feature-names', urlencode([('study', self.study)]))
        names = BitMaskFeatureNames.model_validate(names_obj)
        return list(map(lambda d: d.symbol, names.names))

    def _retrieve_software_versions(self) -> list[SoftwareComponentVersion]:
        versions_obj, _ = self._retrieve('software-component-versions', '')
        versions = list(map(SoftwareComponentVersion.model_validate, versions_obj))
        return versions

    def _one_phenotype_spatial_metric(self, feature_class: str, criteria: PhenotypeCriteria, feature_name: str):
        parts1 = self._form_query_parameters_key_values(criteria)
        parts = parts1 + [('study', self.study), ('feature_class', feature_class)]
        query = urlencode(parts)
        endpoint = 'request-spatial-metrics-computation-custom-phenotype'
        return self._polling_retrieve_values(endpoint, query, feature_name)

    def _polling_retrieve_values(self, endpoint: str, query: str, feature_name: str) -> DataFrame:
        while True:
            response_obj, _ = self._retrieve(endpoint, query)
            response = UnivariateMetricsComputationResult.model_validate(response_obj)
            if response.is_pending and ('SMPROFILER_NO_WAIT' not in os_environ):
                sleep_poll()
            else:
                break
        rows = [
            {'sample': key, feature_name: value}
            for key, value in response.values.items()
        ]
        df = DataFrame(rows).set_index('sample')
        return concat([self.cohorts, self.all_cells, df], axis=1)

    def _form_counts_query(self, p: PhenotypeCriteria) -> tuple[str, str]:
        parts = self._form_query_parameters_key_values(p)
        parts.append(('study', self.study))
        query = urlencode(parts)
        endpoint = 'phenotype-counts'
        return endpoint, query

    def _form_query_parameters_key_values(self, p: PhenotypeCriteria, ordinality: int=1) -> list[tuple[str, str]]:
        positives = p.positive_markers
        negatives = p.negative_markers
        o = '' if ordinality == 1 else str(ordinality)
        if (not positives) and (not negatives):
            raise ValueError('At least one positive or negative marker is required.')
        if not positives:
            positives = ('',)
        elif not negatives:
            negatives = ('',)
        parts = list(chain(*[
            [(f'{keyword}_marker{o}', channel) for channel in argument]
            for keyword, argument in zip(['positive', 'negative'], [positives, negatives])
        ]))
        parts = sorted(list(set(parts)))
        return parts

    def _get_counts_series(self, p: PhenotypeCriteria, column_name: str) -> Series:
        endpoint, query = self._form_counts_query(p)
        counts = PhenotypeCounts.model_validate(self._retrieve(endpoint, query)[0])
        df = DataFrame([model.model_dump() for model in counts.counts])
        mapper = {'specimen': 'sample', 'count': column_name}
        return df.rename(columns=mapper).set_index('sample')[column_name]

    def _retrieve_all_cells_counts(self):
        all_name = 'all cells'
        return self._get_counts_series(PhenotypeCriteria(positive_markers=('',), negative_markers=('',)), all_name)

    def _get_base(self):
        protocol = 'https'
        if self.host == 'localhost' or re.search('127.0.0.1', self.host) or self.use_http:
            protocol = 'http'
        return '://'.join((protocol, self.host))

    def _retrieve(self, endpoint: str, query: str, binary: bool=False):
        base = f'{self._get_base()}'
        url = '/'.join([base, endpoint, '?' + query])
        key = url
        payload = self.cache.lookup(key)
        if payload:
            return self._process_payload(payload, key, binary)
        try:
            start = time()
            headers = {} if not binary else {'Accept-Encoding': 'br'}
            payload = get_request(url, headers=headers)
            end = time()
            key = url
            if binary:
                self.cache.add(key, payload)
            elif 'is_pending' in payload.json() and not payload.json()['is_pending']:
                self.cache.add(key, payload)
            delta = str(end - start)
            now = str(datetime.now())
            with open('requests_timing.txt', 'ta', encoding='utf-8') as file:
                file.write('\t'.join([delta, now, url]) + '\n')
        except Exception as exception:
            print(url)
            raise exception
        return self._process_payload(payload, key, binary)

    def _process_payload(self, payload, key: str, binary: bool) -> tuple[dict | bytes, str]:
        if binary:
            return payload.content, key
        else:
            parsed_payload = payload.json()
            return parsed_payload, key
        #raise ValueError(f'Processing downloaded payload failed: {key}')

@define
class CompareResult:
    pvalue: float
    effect: float
    final_sizes: tuple[int, int]

    def fraction_data_used(self, original_total_size: int) -> float:
        return sum(self.final_sizes) / original_total_size

def univariate_pair_compare_details(series1: Series, series2: Series) -> CompareResult:
    def finite(value):
        return not isnan(value) and not value==inf
    list1 = list(filter(finite, series1.values))
    list2 = list(filter(finite, series2.values))
    null = CompareResult(1.0, inf, (len(list1), len(list2)))
    if len(list1) == 0 or len(list2) == 0:
        return null
    mean1 = float(mean(list1))
    mean2 = float(mean(list2))
    if mean1 == 0:
        return null
    actual = mean2 / mean1
    result = ttest_ind(list1, list2, equal_var=False)
    return CompareResult(
        getattr(result, 'pvalue'),
        actual,
        (len(list1), len(list2)),
    )

def univariate_pair_compare(series1: 'Series[float]', series2: 'Series[float]'):
    cr = univariate_pair_compare_details(series1, series2)
    return cr.pvalue

def append_fractions_feature(
    df: DataFrame,
    column_numerator: str,
    column_denominator: str,
    feature_name: str
) -> DataFrame:
    """
    Forms the fraction column between two provided columns, omitting
    rows for which either numerator or denominator equal to 0.
    """
    fractions = df[column_numerator] / df[column_denominator]
    mask = ~ ( (df[column_numerator] == 0) | (df[column_denominator] == 0) )
    df[feature_name] = fractions
    return df[mask]

def get_fractions(df: DataFrame, column_numerator: str, column_denominator: str, cohort1: str, cohort2: str):
    fractions = df[column_numerator] / df[column_denominator]
    mask = ~ ( (df[column_numerator] == 0) | (df[column_denominator] == 0) )
    fractions1 = fractions[(df['cohort'] == cohort1) & mask]
    fractions2 = fractions[(df['cohort'] == cohort2) & mask]
    return fractions1, fractions2

