"""Utility to report basic health/status of the SMProfiler database."""
import argparse
from itertools import chain

try:
    import pandas as pd
except ModuleNotFoundError as e:
    from smprofiler.standalone_utilities.module_load_error import \
        SuggestExtrasException
    SuggestExtrasException(e, 'db')
import pandas as pd  # pylint: disable=ungrouped-imports

from smprofiler.workflow.tabular_import.parsing.skimmer import DataSkimmer
from smprofiler.db.check_tables import check_tables  # pylint: disable=ungrouped-imports
from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import retrieve_study_names
from smprofiler.workflow.common.cli_arguments import add_argument

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('smprofiler db status')


def report_counts(aggregated):
    if aggregated.shape[0] != 0:
        print(aggregated.sort_values(by='Table').to_string(index=False))
    else:
        print('No datasets present.')


def aggregate_counts(all_counts):
    rows = list(chain(*all_counts))
    df = pd.DataFrame({
        'Table': [row[0] for row in rows],
        'Records': [int(row[1]) for row in rows],
    })
    aggregated = df.groupby('Table').sum()
    aggregated.reset_index(inplace=True)
    return aggregated

def main():
    parser = argparse.ArgumentParser(
        prog='smprofiler db status',
        description='Report basic health status of the given scstudies database.'
    )
    add_argument(parser, 'database config')
    args = parser.parse_args()

    config_file = get_and_validate_database_config(args)
    studies = retrieve_study_names(config_file)
    all_counts = []
    for study in studies:
        with DBCursor(database_config_file=config_file, study=study) as cursor:
            schema_name = DataSkimmer.sanitize_study_to_identifier(study)
            present, counted = check_tables(cursor, schema_name)
            if not present:
                logger.error('Some tables are missing in "%s" database.', study)
            all_counts.append(counted)
    aggregated = aggregate_counts(all_counts)
    report_counts(aggregated)

if __name__ == '__main__':
    main()
