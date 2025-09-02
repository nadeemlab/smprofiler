"""Utility to managed features computed on demand."""
import argparse

from smprofiler.db.ondemand_dropper import OnDemandComputationsDropper
from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler.db.database_connection import DBCursor

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('smprofiler db drop-ondemand-computations')

def main():
    parser = argparse.ArgumentParser(
        prog='smprofiler db drop-ondemand-computations',
        description='Drop ondemand-computed features, including values, specifiers, etc.'
    )
    add_argument(parser, 'database config')
    add_argument(parser, 'study name')
    args = parser.parse_args()

    config_file = get_and_validate_database_config(args)
    with DBCursor(database_config_file=config_file, study=args.study_name) as cursor:
        OnDemandComputationsDropper.drop(cursor)

if __name__ == '__main__':
    main()
