"""Utility to report study names in database."""
import argparse

from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.db.database_connection import DBCursor
from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler.standalone_utilities.module_load_error import SuggestExtrasException
try:
    from smprofiler.db.database_connection import retrieve_study_names
except ModuleNotFoundError as e:
    SuggestExtrasException(e, 'db')
from smprofiler.db.database_connection import retrieve_study_names
from smprofiler.db.accessors.study import StudyAccess

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('smprofiler db count-cells')

def _cache_counts(study: str, database_config_file: str) -> None:
    with DBCursor(database_config_file=database_config_file, study=study) as cursor:
        table = 'all_samples_count'
        cursor.execute(f'CREATE TABLE IF NOT EXISTS {table} (count INTEGER);')
        access = StudyAccess(cursor)
        count = access.get_number_cells(study, verbose=True)
        logger.info(f'Saving: {count} ({study})')
        cursor.execute(f'DELETE FROM {table} ;')
        cursor.execute(f'INSERT INTO {table} VALUES ({count});')

def cache_counts(database_config_file) -> None:
    study_names = retrieve_study_names(database_config_file)
    for study in study_names:
        _cache_counts(study, database_config_file)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler db count-cells',
        description='Store cell counts for all datasets.'
    )
    add_argument(parser, 'database config')
    args = parser.parse_args()

    config_file = get_and_validate_database_config(args)
    cache_counts(config_file)
