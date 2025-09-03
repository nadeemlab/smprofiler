"""Synchronize study/channel annotations in JSON file with database."""

import argparse
from json import loads as json_loads
from typing import cast

from psycopg import sql as psycopg_sql

from smprofiler.db.scripts.interactive_uploader import InteractiveUploader as DatabaseSelector
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.exchange_data_formats.study import ChannelGroupAnnotation

from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger('sync_annotations')


class SyncAnnotations:
    database_config_file: str

    def __init__(self, annotations_file: str, database_config_file: str | None):
        if database_config_file is None:
            self._database_connection_setup()
        else:
            self.database_config_file = database_config_file
        self._sync(annotations_file)

    def _database_connection_setup(self) -> None:
        database_selector = DatabaseSelector()
        database_selector._assess_database_config_files()
        database_selector._solicit_and_ensure_database_selection()
        self.database_config_file = cast(str, database_selector.selected_database_config_file)

    def _sync(self, annotations_file: str) -> None:
        with open(annotations_file, 'rt', encoding='utf-8') as file:
            contents = file.read()
        annotations = json_loads(contents)
        rows_groups = self._form_rows(annotations)
        self._create_tables()
        self._clear_tables()
        self._insert(*rows_groups)

    def _form_rows(self, annotations: dict) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
        groups: dict[str, ChannelGroupAnnotation] = annotations['groups']
        aliases: dict[str, str] = annotations['aliases']
        channel_groups = tuple((name, group['color']) for name, group in groups.items())
        channel_in_groups = tuple(
            (c, name)
            for name, group in groups.items()
            for c in group['channels']
        )
        channel_aliases = tuple( aliases.items() )
        return (channel_groups, channel_in_groups, channel_aliases)

    def _create_tables(self) -> None:
        with DBCursor(database_config_file=self.database_config_file) as cursor:
            annotations_schema = '''
            CREATE TABLE IF NOT EXISTS channel_group(
                name VARCHAR(256) PRIMARY KEY,
                color VARCHAR(256)
            );

            CREATE TABLE IF NOT EXISTS channel_in_group(
                channel_specific VARCHAR(256),
                _group VARCHAR(256) REFERENCES channel_group ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS channel_alias(
                channel_specific VARCHAR(256),
                alias VARCHAR(256)
            )
            '''
            cursor.execute(annotations_schema)

    def _clear_tables(self) -> None:
        with DBCursor(database_config_file=self.database_config_file) as cursor:
            for t in ('channel_group', 'channel_in_group', 'channel_alias'):
                cursor.execute('DELETE FROM %s ;' % t)

    def _insert(self, *args) -> None:
        with DBCursor(database_config_file=self.database_config_file) as cursor:
            for table, rows in zip(('channel_group', 'channel_in_group', 'channel_alias'), args):
                for row in rows:
                    cursor.execute(
                        psycopg_sql.SQL('INSERT INTO {} VALUES (%s, %s);').format(psycopg_sql.Identifier(table)),
                        (*row,),
                    )


def parse_args():
    parser = argparse.ArgumentParser(
        prog='smprofiler db sync-annotations',
        description='Synchronize presentation-layer annotations for channels.'
    )
    parser.add_argument(
        'annotations_file',
        type=str,
        help='The JSON file containing the annotations.',
    )
    parser.add_argument(
        '--database-config-file',
        type=str,
        default=None,
        help='Optional, if not provided the interactive dialog will solicit this.',
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    s = SyncAnnotations(cast(str, args.annotations_file), args.database_config_file)
