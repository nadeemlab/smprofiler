"""Synchronize a small data artifact with the database."""

import argparse
from json import loads as json_loads

from psycopg import Cursor as PsycopgCursor

from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.db.database_connection import DBCursor
from smprofiler.workflow.common.cli_arguments import add_argument

from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger('upload_sync_small')

APPROVED_NAMES = ('findings', 'gnn_plot_configurations', 'curation_notes')


def parse_args():
    parser = argparse.ArgumentParser(
        prog='smprofiler db upload-sync-small',
        description='Synchronize small lists of strings for each study with the database.'
    )
    parser.add_argument(
        'name',
        choices=APPROVED_NAMES,
        help='The name of the table of strings to be synchronized.',
    )
    parser.add_argument(
        'file',
        help='The JSON file containing the list of strings to be synced for each study.',
    )
    add_argument(parser, 'database config')
    return parser.parse_args()


def _create_table_query(name: str) -> str:
    return f'CREATE TABLE IF NOT EXISTS {name} (id SERIAL PRIMARY KEY, txt TEXT);'


def _sync_data(cursor: PsycopgCursor, name: str, data: tuple[str, ...]) -> bool:
    cursor.execute(_create_table_query(name))
    cursor.execute(f'SELECT id, txt FROM {name} ORDER BY id;')
    rows = tuple(cursor.fetchall())
    if tuple(text for _, text in rows) == data:
        return True
    cursor.execute(f'DELETE FROM {name};')
    for datum in data:
        cursor.execute(f'INSERT INTO {name}(txt) VALUES (%s);', (datum,))
    return False


def _upload_sync_study(
    study: str,
    name: str,
    data: list[str],
    database_config_file: str,
) -> None:
    with DBCursor(database_config_file=database_config_file, study=study) as cursor:
        already_synced = _sync_data(cursor, name, tuple(data))
        if already_synced:
            logger.info(f'Data for "{study}" are already up-to-date.')
        else:
            logger.info(f'Data for "{study}" were synced.')


def upload_sync(
    name: str,
    data_per_study: dict[str, list[str]],
    database_config_file: str,
) -> None:
    for study, study_data in data_per_study.items():
        _upload_sync_study(study, name, study_data, database_config_file)


def main():
    args = parse_args()
    database_config_file = get_and_validate_database_config(args)
    with open(args.file, 'rt', encoding='utf-8') as file:
        contents = file.read()
    to_sync = json_loads(contents)
    upload_sync(args.name, to_sync, database_config_file)


if __name__ == '__main__':
    main()
