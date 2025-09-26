from importlib.resources import as_file
from importlib.resources import files
from json import loads as json_loads
import argparse

from pandas import read_csv as pandas_read_csv

from smprofiler.workflow.tabular_import.parsing.diagnosis import DiagnosisParser
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.workflow.common.cli_arguments import add_argument


def parse_args():
    parser = argparse.ArgumentParser(
        prog='smprofiler db sync-table',
        description='Synchronize database table with a file artifact.'
    )
    add_argument(parser, 'database config')
    parser.add_argument(
        '--table-name',
        dest='table_name',
        choices=available_for_sync(),
        required=True,
    )
    parser.add_argument(
        '--study-json',
        dest='study_json',
        required=False,
        help='The study.json file for the study (provides study name).',
    )
    parser.add_argument(
        '--study-name',
        dest='study_name',
        required=False,
        help='The study name (if study.json is not provided).',
    )
    parser.add_argument(
        '--source-file',
        dest='source_file',
        required=True,
        help='The source file to search for records to be uploaded or synced.',
    )
    parser.add_argument(
        '--drop-first',
        dest='drop_first',
        action='store_true',
        help='Indicates whether to drop all records in the remote table before attempting upload.',
    )
    return parser.parse_args()

def available_for_sync() -> tuple[str, ...]:
    return ('diagnosis',)

def sync_table(table: str, study: str, database_config_file: str, source_file: str, drop_first: bool) -> None:
    if table == 'diagnosis':
        with as_file(files('adiscstudies').joinpath('fields.tsv')) as path:
            fields = pandas_read_csv(path, sep='\t', na_filter=False)
        with DBConnection(database_config_file=database_config_file, study=study) as connection:
            DiagnosisParser(fields).parse(connection, source_file, drop_first=drop_first)
        return
    raise ValueError(f'Table "{table}" is not a supported sync target.')

def main():
    args = parse_args()
    database_config_file = get_and_validate_database_config(args)
    study_name = None
    if args.study_json:
        with open(args.study_json, 'rt', encoding='utf-8') as file:
            study_name = json_loads(file.read())['Study name']
    else:
        study_name = args.study_name
    sync_table(args.table_name, study_name, database_config_file, args.source_file, args.drop_first)

if __name__=='__main__':
    main()

