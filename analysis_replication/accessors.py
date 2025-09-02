"""Convenience caller of HTTP methods for data access."""
from typing import cast
import re
from itertools import chain
from urllib.parse import urlencode
from requests import get as get_request  # type: ignore
from os.path import exists
from time import sleep
from time import time
from datetime import datetime
from sqlite3 import connect
import pickle

from pandas import DataFrame
from pandas import concat
from numpy import inf
from numpy import nan
from numpy import isnan
from numpy import mean
from numpy import log
from scipy.stats import ttest_ind  # type: ignore
from sklearn.metrics import auc  # type:ignore

from smprofiler.standalone_utilities.float8 import decode as decode_float8


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


class Colors:
    bold_green = '\u001b[32;1m'
    blue = '\u001b[34m'
    bold_magenta = '\u001b[35;1m'
    bold_red = '\u001b[31;1m'
    yellow = '\u001b[33m'
    reset = '\u001b[0m'


def sleep_poll():
    seconds = 10
    print(f'Waiting {seconds} seconds to poll.')
    sleep(seconds)


class DataAccessor:
    """Convenience caller of HTTP methods for data access."""
    caching: bool

    def __init__(self, study, host=None, caching: bool=True):
        self.caching = caching
        if self.caching:
            with connect('cache.sqlite3') as connection:
                cursor = connection.cursor()
                cursor.execute('CREATE TABLE IF NOT EXISTS cache(url TEXT, contents BLOB);')
        _host = get_default_host(host)
        if _host is None:
            raise RuntimeError('Expected host name in api_host.txt .')
        host = _host
        use_http = False
        if re.search('^http://', host):
            use_http = True
            host = re.sub(r'^http://', '', host)
        self.host = host
        self.study = study
        self.use_http = use_http
        print('\n' + Colors.bold_magenta + study + Colors.reset + '\n')
        self.cohorts = self._retrieve_cohorts()
        self.all_cells = self._retrieve_all_cells_counts()

    def feature_matrix(self, sample: str) -> DataFrame:
        parts = [
            ('study', self.study),
            ('sample', sample),
        ]
        query = urlencode(parts)
        endpoint = 'cell-data-binary-intensity'
        blob, url = self._retrieve(endpoint, query, binary=True)
        names = self._retrieve_feature_names()
        rows = self._extract_rows(blob, len(names))
        return DataFrame(rows, columns=names)

    def _retrieve_feature_names(self) -> list[str]:
        names, _ = self._retrieve('cell-data-binary-feature-names', urlencode([('study', self.study)]))
        return list(map(lambda d: d['symbol'], names['names']))

    def _extract_rows(self, binary_matrix: bytes, number_columns: int) -> list[tuple]:
        number_cells = self._get_number_cells(binary_matrix, number_columns)
        global_offset = 0
        local_offset = 4
        rows = []
        def position(index: int, frame: int) -> int:
            return global_offset + local_offset + (frame * (number_columns + local_offset)) + index
        for frame in range(number_cells):
            row = tuple(
                decode_float8(binary_matrix[position(i, frame): position(i, frame) + 1])
                for i in range(number_columns)
            )
            rows.append(row)
        return rows

    def _get_number_cells(self, binary_matrix: bytes, number_columns: int) -> int:
        return len(binary_matrix) // (number_columns + 4)

    def counts(self, phenotype_names):
        if isinstance(phenotype_names, str):
            phenotype_names = [phenotype_names]
        conjunction_criteria = self._conjunction_phenotype_criteria(phenotype_names)
        all_name = self.name_for_all_phenotypes(phenotype_names)
        conjunction_counts_series = self._get_counts_series(conjunction_criteria, all_name)
        individual_counts_series = [
            self._get_counts_series(self._phenotype_criteria(name), self._name_phenotype(name))
            for name in phenotype_names
        ]
        df = concat(
            [self.cohorts, self.all_cells, conjunction_counts_series, *individual_counts_series],
            axis=1,
        )
        df.replace([inf, -inf], nan, inplace=True)
        return df

    def name_for_all_phenotypes(self, phenotype_names):
        return ' and '.join([self._name_phenotype(p) for p in phenotype_names])

    def neighborhood_enrichment(self, phenotype_names):
        feature_class = 'neighborhood enrichment'
        return self._two_phenotype_spatial_metric(phenotype_names, feature_class)

    def co_occurrence(self, phenotype_names):
        feature_class = 'co-occurrence'
        return self._two_phenotype_spatial_metric(phenotype_names, feature_class)

    def proximity(self, phenotype_names):
        feature_class = 'proximity'
        return self._two_phenotype_spatial_metric(phenotype_names, feature_class)

    def spatial_autocorrelation(self, phenotype_name):
        feature_class = 'spatial autocorrelation'
        return self._one_phenotype_spatial_metric([phenotype_name], feature_class)

    def _one_phenotype_spatial_metric(self, phenotype_names, feature_class):
        criteria = [self._phenotype_criteria(p) for p in phenotype_names]
        names = [self._name_phenotype(p) for p in phenotype_names]

        positives = criteria[0]['positive_markers']
        negatives = criteria[0]['negative_markers']
        parts1 = list(chain(*[
            [(f'{keyword}_marker', channel) for channel in argument]
            for keyword, argument in zip(['positive', 'negative'], [positives, negatives])
        ]))

        parts = parts1 + [('study', self.study), ('feature_class', feature_class)]
        query = urlencode(parts)
        endpoint = 'request-spatial-metrics-computation-custom-phenotype'

        while True:
            response, url = self._retrieve(endpoint, query)
            if response['is_pending'] is True:
                sleep_poll()
            else:
                break

        rows = [
            {'sample': key, '%s, %s' % (feature_class, ' and '.join(names)): value}
            for key, value in response['values'].items()
        ]
        df = DataFrame(rows).set_index('sample')
        return concat([self.cohorts, self.all_cells, df], axis=1)

    def _two_phenotype_spatial_metric(self, phenotype_names, feature_class):
        criteria = [self._phenotype_criteria(p) for p in phenotype_names]
        names = [self._name_phenotype(p) for p in phenotype_names]

        positives = criteria[0]['positive_markers']
        negatives = criteria[0]['negative_markers']
        parts1 = list(chain(*[
            [(f'{keyword}_marker', channel) for channel in argument]
            for keyword, argument in zip(['positive', 'negative'], [positives, negatives])
        ]))

        positives = criteria[1]['positive_markers']
        negatives = criteria[1]['negative_markers']
        parts2 = list(chain(*[
            [(f'{keyword}_marker2', channel) for channel in argument]
            for keyword, argument in zip(['positive', 'negative'], [positives, negatives])
        ]))

        parts = parts1 + parts2 + [('study', self.study), ('feature_class', feature_class)]
        if feature_class == 'co-occurrence':
            parts.append(('radius', '100'))
        if feature_class == 'proximity':
            parts.append(('radius', '100'))
        query = urlencode(parts)
        endpoint = 'request-spatial-metrics-computation-custom-phenotypes'

        while True:
            response, url = self._retrieve(endpoint, query)
            if response['is_pending'] is True:
                sleep_poll()
            else:
                break

        rows = [
            {'sample': key, '%s, %s' % (feature_class, ' and '.join(names)): value}
            for key, value in response['values'].items()
        ]
        df = DataFrame(rows).set_index('sample')
        return concat([self.cohorts, self.all_cells, df], axis=1)

    def counts_by_signature(self, positives: list[str], negatives: list[str]):
        if (not positives) and (not negatives):
            raise ValueError('At least one positive or negative marker is required.')
        if not positives:
            positives = ['']
        elif not negatives:
            negatives = ['']
        parts = list(chain(*[
            [(f'{keyword}_marker', channel) for channel in argument]
            for keyword, argument in zip(['positive', 'negative'], [positives, negatives])
        ]))
        parts = sorted(list(set(parts)))
        parts.append(('study', self.study))
        query = urlencode(parts)
        endpoint = 'anonymous-phenotype-counts-fast'
        return self._retrieve(endpoint, query)[0]

    def _get_counts_series(self, criteria, column_name):
        criteria_tuple = (
            criteria['positive_markers'],
            criteria['negative_markers'],
        )
        counts = self.counts_by_signature(*criteria_tuple)
        df = DataFrame(counts['counts'])
        mapper = {'specimen': 'sample', 'count': column_name}
        return df.rename(columns=mapper).set_index('sample')[column_name]

    def _retrieve_cohorts(self):
        summary, _ = self._retrieve('study-summary', urlencode([('study', self.study)]))
        return DataFrame(summary['cohorts']['assignments']).set_index('sample')

    def _retrieve_all_cells_counts(self):
        counts = self.counts_by_signature([''], [''])
        df = DataFrame(counts['counts'])
        all_name = 'all cells'
        mapper = {'specimen': 'sample', 'count': all_name}
        counts_series = df.rename(columns=mapper).set_index('sample')[all_name]
        return counts_series

    def _get_base(self):
        protocol = 'https'
        if self.host == 'localhost' or re.search('127.0.0.1', self.host) or self.use_http:
            protocol = 'http'
        return '://'.join((protocol, self.host))

    def _add_to_cache(self, url, contents):
        if not self.caching:
            return
        with connect('cache.sqlite3') as connection:
            cursor = connection.cursor()
            cursor.execute('INSERT INTO cache(url, contents) VALUES (?, ?);', (url, pickle.dumps(contents)))

    def _drop_from_cache(self, url: str) -> None:
        with connect('cache.sqlite3') as connection:
            cursor = connection.cursor()
            cursor.execute('DELETE FROM cache WHERE url=?;', (url,))

    def _lookup_cache(self, url, binary: bool=False):
        if not self.caching:
            return None
        with connect('cache.sqlite3') as connection:
            cursor = connection.cursor()
            cursor.execute('SELECT contents FROM cache WHERE url=?;', (url,))
            rows = cursor.fetchall()
            if len(rows) > 0:
                if binary:
                    obj = pickle.loads(rows[0][0], encoding='bytes')
                else:
                    obj = pickle.loads(rows[0][0], encoding='bytes').json()
                return obj, url
        return None

    def _retrieve(self, endpoint, query, binary: bool=False):
        base = f'{self._get_base()}'
        url = '/'.join([base, endpoint, '?' + query])
        c = self._lookup_cache(url, binary=binary)
        if c:
            if binary:
                return c[0].content, c[1]
            if 'is_pending' in c[0]:
                if not c[0]['is_pending']:
                    return c
            else:
                return c
        try:
            start = time()
            headers = {} if not binary else {'Accept-Encoding': 'br'}
            content = get_request(url, headers=headers)
            end = time()
            self._add_to_cache(url, content)
            delta = str(end - start)
            now = str(datetime.now())
            with open('requests_timing.txt', 'ta', encoding='utf-8') as file:
                file.write('\t'.join([delta, now, url]) + '\n')
        except Exception as exception:
            print(url)
            raise exception
        if binary:
            return content.content, url
        return content.json(), url

    def _phenotype_criteria(self, name):
        if isinstance(name, dict):
            criteria = name
            keys = ['positive_markers', 'negative_markers']
            for key in keys:
                if criteria[key] == []:
                    criteria[key] = ['']
            return criteria
        query = urlencode([('study', self.study), ('phenotype_symbol', name)])
        criteria, _ = self._retrieve('phenotype-criteria', query)
        return criteria

    def _conjunction_phenotype_criteria(self, names):
        criteria_list = []
        for name in names:
            criteria = self._phenotype_criteria(name)
            criteria_list.append(criteria)
        return self._merge_criteria(criteria_list)

    def _merge_criteria(self, criteria_list):
        keys = ['positive_markers', 'negative_markers']
        merged = {
            key: sorted(list(set(list(chain(*[criteria[key] for criteria in criteria_list])))))
            for key in keys
        }
        for key in keys:
            if merged[key] == []:
                merged[key] = ['']
        return merged

    def _name_phenotype(self, phenotype):
        if isinstance(phenotype, dict):
            return ' '.join([
                ' '.join([f'{p}{sign}' for p in phenotype[f'{keyword}_markers'] if p != ''])
                for keyword, sign in zip(['positive', 'negative'], ['+', '-'])
            ]).rstrip()
        return str(phenotype)

    def important(
        self,
        phenotype_names: str | list[str],
        plugin: str = 'cg-gnn',
        datetime_of_run: str | None = None,
        plugin_version: str | None = None,
        cohort_stratifier: str | None = None,
    ) -> dict[str, float]:
        if isinstance(phenotype_names, str):
            phenotype_names = [phenotype_names]
        conjunction_criteria = self._conjunction_phenotype_criteria(phenotype_names)
        parts = list(chain(*[
            [(f'{keyword}_marker', channel) for channel in argument]
            for keyword, argument in zip(
                ['positive', 'negative'], [
                    conjunction_criteria['positive_markers'],
                    conjunction_criteria['negative_markers'],
                ])
        ]))
        parts = sorted(list(set(parts)))
        parts.append(('study', self.study))
        if plugin in {'cg-gnn', 'graph-transformer'}:
            parts.append(('plugin', plugin))
        else:
            raise ValueError(f'Unrecognized plugin name: {plugin}')
        if datetime_of_run is not None:
            parts.append(('datetime_of_run', datetime_of_run))
        if plugin_version is not None:
            parts.append(('plugin_version', plugin_version))
        if cohort_stratifier is not None:
            parts.append(('cohort_stratifier', cohort_stratifier))
        query = urlencode(parts)
        phenotype_counts, _ = self._retrieve('importance-composition', query)
        return {c['specimen']: c['percentage'] for c in phenotype_counts['counts']}


class ExpectedQuantitativeValueError(ValueError):
    """
    Raised when an expected quantitative result is significantly different from the expected value.
    """
    message: str

    def __init__(self, expected: float, actual: float):
        error_percent = self.error_percent(expected, actual)
        if error_percent is not None:
            error_percent = round(100 * error_percent) / 100
        message = f'''
        Expected {expected} but got {Colors.bold_red}{actual}{Colors.reset}. Error is {error_percent}%.
        '''
        self.message = message
        super().__init__(message)

    def print(self) -> None:
        print(self.message)

    @staticmethod
    def is_error(expected: float, actual: float) -> bool:
        error_percent = ExpectedQuantitativeValueError.error_percent(expected, actual)
        if error_percent is None:
            return True
        if error_percent < 1.0:
            return False
        return True

    @staticmethod
    def error_percent(expected: float, actual: float) -> float | None:
        if actual != 0:
            error_percent = abs(100 * (1 - (actual / expected)))
        else:
            error_percent = None
        return error_percent


def handle_expected_actual(expected: float, actual: float | None):
    _actual = cast(float, actual)
    if ExpectedQuantitativeValueError.is_error(expected, _actual):
        error = ExpectedQuantitativeValueError(expected, _actual)
        error.print()
    string = str(_actual)
    padded = string + ' '*(21 - len(string))
    print(Colors.bold_green + padded + Colors.reset, end='')


def compute_auc(list1: list[float], list2: list[float]) -> float:
    pairs = [(value, 0) for value in list1] + [(value, 1) for value in list2]
    pairs.sort(key=lambda pair: pair[0])
    total_labelled = sum([pair[1] for pair in pairs])
    total_unlabelled = len(pairs) - total_labelled
    graph_points = [(0.0, 1.0)]
    true_positives = 0
    true_negatives = total_unlabelled
    for _, label in pairs:
        if label == 1:
            true_positives = true_positives + 1
        else:
            true_negatives = true_negatives - 1
        graph_points.append((true_positives / total_labelled, true_negatives / total_unlabelled))
    _auc = auc([p[0] for p in graph_points], [p[1] for p in graph_points])
    _auc = max(_auc, 1 - _auc)
    return _auc


def univariate_pair_compare(
    list1,
    list2,
    expected_fold=None,
    do_log_fold: bool = False,
    show_pvalue=False,
    show_auc=False,
):
    list1 = list(filter(lambda element: not isnan(element) and not element==inf, list1.values))
    list2 = list(filter(lambda element: not isnan(element) and not element==inf, list2.values))

    mean1 = float(mean(list1))
    mean2 = float(mean(list2))
    actual = mean2 / mean1
    if expected_fold is not None:
        handle_expected_actual(expected_fold, actual)
    print((mean2, mean1, actual), end='')

    if do_log_fold:
        _list1 = [log(e) for e in list(filter(lambda element: element != 0, list1))]
        _list2 = [log(e) for e in list(filter(lambda element: element != 0, list2))]
        _mean1 = float(mean(_list1))
        _mean2 = float(mean(_list2))
        log_fold = _mean2 / _mean1
        print('  log fold: ' + Colors.yellow + str(log_fold) + Colors.reset, end='')

    if show_pvalue:
        if do_log_fold:
            result = ttest_ind(_list1, _list2, equal_var=False)
            print(
                '  p-value (after log): ' + Colors.blue + str(result.pvalue) + Colors.reset, end=''
            )
        else:
            result = ttest_ind(list1, list2, equal_var=False)
            print('  p-value: ' + Colors.blue + str(result.pvalue) + Colors.reset, end='')

    if show_auc:
        _auc = compute_auc(list1, list2)
        print('  AUC: ' + Colors.blue + str(_auc) + Colors.reset, end='')

    print('')


def get_fractions(df, column_numerator, column_denominator, cohort1, cohort2, omit_zeros=True):
    fractions = df[column_numerator] / df[column_denominator]
    if omit_zeros:
        mask = ~ ( (df[column_numerator] == 0) | (df[column_denominator] == 0) )
        total1 = sum((df['cohort'] == cohort1))
        omit1 = total1 - sum((df['cohort'] == cohort1) & mask)
        total2 = sum((df['cohort'] == cohort2))
        omit2 = total2 - sum((df['cohort'] == cohort2) & mask)
        if omit1 !=0 or omit2 !=0:
            print(f'(Omitting {omit1}/{total1} from {cohort1} and {omit2}/{total2} from {cohort2}.)')
    else:
        mask = True
    fractions1 = fractions[(df['cohort'] == cohort1) & mask]
    fractions2 = fractions[(df['cohort'] == cohort2) & mask]
    return fractions1, fractions2
