"""Test pulling out of stratification for cohorts from database."""
import pandas as pd

from smprofiler.db.stratification_puller import StratificationPuller


def test_stratification_puller(measured_only: bool):
    database_config_file='../workflow/.smprofiler_db.config.container'
    puller = StratificationPuller(database_config_file)
    puller.pull(measured_only=measured_only)
    stratification = puller.get_stratification()

    prefix = 'measured' if measured_only else 'all'
    filename = f'unit_tests/strata {prefix}/expected_stratification_assignments.tsv'
    expected_assignments = pd.read_csv(filename, sep='\t', dtype=object)
    assignment_rows = set(tuple(list(row)) for _, row in expected_assignments.iterrows())
    expected_strata = pd.read_csv(f'unit_tests/strata {prefix}/expected_strata.tsv', sep='\t', dtype=object)
    stratum_rows = set(tuple(list(row)) for _, row in expected_strata.iterrows())

    for _, stratification_study in stratification.items():
        df = stratification_study['assignments']
        rows2 = set(tuple(list(row)) for _, row in df.iterrows())
        if assignment_rows != rows2:
            print(f'Wrong assignments set: {rows2}')
            print(f'Expected: f{assignment_rows}')
            raise ValueError('Wrong assignments set.')

        strata = stratification_study['strata']
        rows3 = set(tuple(list(row)) for _, row in strata.iterrows())
        if stratum_rows != rows3:
            print(f'Wrong stratum set: {rows3}')
            print(f'Expected: {stratum_rows}')
            raise ValueError('Wrong stratum set.')


if __name__ == '__main__':
    print('Selecting all specimens')
    test_stratification_puller(measured_only=False)
    print('Selecting measured specimens only')
    test_stratification_puller(measured_only=True)
