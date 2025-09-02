"""
CLI utility to drop a study from an ADI-formatted database.
"""
import argparse

from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.db.study_dropper import StudyDropper
from smprofiler.workflow.common.cli_arguments import add_argument

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('smprofiler db drop')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler db drop',
        description='Drop one study\'s worth of data.'
    )
    add_argument(parser, 'database config')
    parser.add_argument(
        '--study-name',
        dest='study_name',
        help='The name of the study to drop.',
    )
    args = parser.parse_args()

    database_config_file = get_and_validate_database_config(args)
    StudyDropper.drop(database_config_file, study=args.study_name)
