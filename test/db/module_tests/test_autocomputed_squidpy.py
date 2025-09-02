"""
Test the computation and saving of the Squidpy metrics that depend on a single phenotype, and so
can be computed automatically after data import if desired.
"""

from pandas import read_csv
from pandas import DataFrame
from numpy import isnan

from smprofiler.db.squidpy_metrics import create_and_transcribe_squidpy_features
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.describe_features import get_feature_description

FeatureVector = tuple[tuple[str, float], ...]

def get_expected_records():
    filename = 'module_tests/expected_auto_correlations.tsv'
    df = read_csv(filename, sep='\t', header=None)
    df.columns = ['feature', 'sample', 'value']
    df['feature'] = df['feature'].astype(str)
    df['sample'] = df['sample'].astype(str)
    df['value'] = df['value'].astype(float)
    df['value'] = df['value'].apply(round3)
    return extract_feature_vectors(df)


def extract_feature_vectors(df: DataFrame) -> list[FeatureVector]:
    return [
        create_feature_vector(_df)
        for _, _df in df.groupby('feature')
    ]
    

def create_feature_vector(df: DataFrame) -> FeatureVector:
    rows = [(row['sample'], row['value']) for i, row in df.iterrows()]
    return tuple(sorted(rows, key=lambda x: x[0]))


def check_records(feature_values):
    rows = [(row[0], row[1], round3(row[2])) for row in feature_values]
    df = DataFrame(rows, columns=['feature', 'sample', 'value'])
    feature_vectors = extract_feature_vectors(df)
    missing = set(get_expected_records()).difference(feature_vectors)
    if len(missing) > 0:
        with open('module_tests/_expected_auto_correlations.tsv', 'wt', encoding='utf-8') as file:
            count = 1
            for feature_vector in feature_vectors:
                for entry in feature_vector:
                    file.write('\t'.join([str(count)] + [str(e) for e in entry]))
                    file.write('\n')
                count += 1
        newline = '\n'
        _expected = newline.join(str(x) for x in sorted(missing))
        _got = newline.join(str(x) for x in sorted(rows))
        raise ValueError(f'Expected to find records: {_expected}\nGot: {_got}')

    print('All expected records found.')
    unexpected = set(feature_vectors).difference(get_expected_records())
    if len(unexpected) > 0:
        raise ValueError(f'Got some unexpected records: {unexpected}')
    print('No unexpected records encountered.')


def round3(value):
    return round(value, ndigits=3)


def retrieve_feature_values(connection):
    cursor = connection.cursor()
    cursor.execute(f'''
    SELECT fs.identifier, qfv.subject, qfv.value FROM quantitative_feature_value qfv
    JOIN feature_specification fs ON fs.identifier=qfv.feature
    WHERE fs.derivation_method='{get_feature_description("spatial autocorrelation")}'
    ;
    ''')
    rows = cursor.fetchall()
    cursor.close()
    return [
        (row[0], row[1], float(row[2]))
        for row in rows if row[2] is not None and not isnan(float(row[2]))
    ]


def test_autocomputed_squidpy_features():
    database_config_file='.smprofiler_db.config.container'
    study = 'Melanoma intralesional IL2'
    create_and_transcribe_squidpy_features(database_config_file, study)
    with DBConnection(database_config_file=database_config_file, study=study) as connection:
        feature_values = retrieve_feature_values(connection)
    print('\n'.join([str(r) for r in feature_values[0:10]] + ['...']))
    check_records(feature_values)


if __name__=='__main__':
    test_autocomputed_squidpy_features()
