"""Simple statistical significance testing of single features along pairs of cohorts."""

from itertools import combinations
from math import isnan

import pandas as pd
from scipy.stats import ttest_ind  # type: ignore

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def perform_tests(data_analysis_study, connection):
    """For each of the given study's features, do tests for significant difference
    between each pair of cohorts. Currently using t-test.
    """
    feature_values = retrieve_feature_values(data_analysis_study, connection)
    if tests_already_recorded(feature_values, connection):
        return
    test_results = do_tests_on_feature_values(feature_values)
    insert_test_results(test_results, connection)

def retrieve_feature_values(data_analysis_study, connection):
    feature_extraction_query = '''
    SELECT
        qfv.feature,
        qfv.value,
        ss.stratum_identifier
    FROM
        quantitative_feature_value qfv
    JOIN feature_specification fs ON qfv.feature = fs.identifier
    JOIN sample_strata ss ON qfv.subject = ss.sample
    WHERE fs.study=%s ;
    '''
    cursor = connection.cursor()
    cursor.execute(feature_extraction_query, (data_analysis_study,))
    rows = cursor.fetchall()
    cursor.close()
    columns = ['feature', 'value', 'stratum_identifier']
    return pd.DataFrame(rows, columns=columns)

def do_tests_on_feature_values(feature_values):
    cohort_identifiers = sorted(list(feature_values['stratum_identifier'].unique()))
    cohort_pairs = list(combinations(cohort_identifiers, 2))
    test_results = []
    for feature, df in feature_values.groupby('feature'):
        for cohort1, cohort2 in cohort_pairs:
            values1 = [float(v) for v in df[df['stratum_identifier'] == cohort1]['value']]
            values2 = [float(v) for v in df[df['stratum_identifier'] == cohort2]['value']]
            if len(values1) < 2 or len(values2) < 2:
                continue
            ttest = ttest_ind(values1, values2)
            if isnan(ttest.pvalue):
                continue
            test_results.append((cohort1, cohort2, 't-test', ttest.pvalue, feature))
    return test_results

def insert_test_results(test_results, connection):
    cursor = connection.cursor()
    insert_query = '''
    INSERT INTO
    two_cohort_feature_association_test (
        selection_criterion_1,
        selection_criterion_2,
        test,
        p_value,
        feature_tested)
    VALUES (%s, %s, %s, %s, %s) ;
    '''
    cursor.executemany(insert_query, test_results)
    cursor.close()
    connection.commit()

def tests_already_recorded(feature_values, connection):
    features = list(feature_values['feature'].unique())
    cursor = connection.cursor()
    cursor.execute('''
    SELECT feature_tested
    FROM two_cohort_feature_association_test
    WHERE test=%s
    ;
    ''', ('t-test',))
    tested_features = [row[0] for row in cursor.fetchall()]
    cursor.close()
    if len(set(features).intersection(set(tested_features))) > 0:
        return True
    return False
