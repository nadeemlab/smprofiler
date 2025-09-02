"""Test that transcription of importance scores from GNN output into the database succeeds."""
from pandas import DataFrame

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.importance_score_transcriber import transcribe_importance
from smprofiler.db.describe_features import get_feature_description


def get_test_importance_rows():
    return [
        (119, 0.80),
        (120, 0.81),
        (121, 0.82),
        (122, 0.83),
        (123, 0.84),
        (124, 0.85),
        (125, 0.86),
        (126, 0.10),
    ]


def get_expected_records():
    return [
        (119, 7),
        (120, 6),
        (121, 5),
        (122, 4),
        (123, 3),
        (124, 2),
        (125, 1),
        (126, 8),
    ]


def check_records(feature_values):
    rows = [(row[0], row[1]) for row in feature_values]
    missing = set(get_expected_records()).difference(rows)
    if len(missing) > 0:
        raise ValueError(f'Expected to find records: {missing}\nGot only: {rows}')
    print('All expected records found.')
    unexpected = set(rows).difference(get_expected_records())
    if len(unexpected) > 0:
        raise ValueError(f'Got some unexpected records: {unexpected}')
    print('No unexpected records encountered.')


def retrieve_feature_values(connection):
    cursor = connection.cursor()
    cursor.execute(f'''
    SELECT * FROM quantitative_feature_value qfv
    JOIN feature_specification fs ON fs.identifier=qfv.feature
    WHERE fs.derivation_method='{get_feature_description("gnn importance score")}'
    ;
    ''')
    rows = cursor.fetchall()
    cursor.close()
    return [(int(row[2]), int(row[3])) for row in rows]


def test_transcribe_importances():
    columns = ['histological_structure', 'importance']
    df = DataFrame(get_test_importance_rows(), columns=columns)
    df = df.set_index('histological_structure')
    database_config_file = '../db/.smprofiler_db.config.container'
    study = 'Melanoma intralesional IL2'
    transcribe_importance(
        df,
        database_config_file,
        study,
        'cg-gnn',
        'October 2, 2023 10:16 AM',
    )
    with DBConnection(database_config_file=database_config_file, study=study) as connection:
        feature_values = retrieve_feature_values(connection)
    check_records(feature_values)


if __name__ == '__main__':
    test_transcribe_importances()
