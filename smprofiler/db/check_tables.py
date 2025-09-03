"""Convenience function providing summary of number of records per table."""
from importlib.resources import as_file
from importlib.resources import files

import pandas as pd
from psycopg import Cursor as PsycopgCursor

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def check_tables(cursor: PsycopgCursor, schema: str) -> tuple[bool, list[tuple[str, int]]]:
    with as_file(files('adiscstudies').joinpath('tables.tsv')) as path:
        tables = pd.read_csv(path, sep='\t', keep_default_na=False)
    table_names: list[str] = list(tables['Name'])
    cursor.execute('SELECT tablename FROM pg_tables WHERE schemaname=%s ;', (schema,))
    values = list(map(lambda row: row[0], cursor.fetchall()))
    missing = list(set(table_names).difference(values))
    if len(missing) == 0:
        tables_present = True
    else:
        logger.error('Expected table(s) not found: %s', missing)
        tables_present = False
    counts: list[tuple[str, int]] = []
    for tablename in table_names:
        cursor.execute(f'SELECT COUNT(*) FROM {tablename} ;')
        rows = tuple(cursor.fetchall())
        count = int(rows[0][0])
        counts.append((tablename, count))
    return tables_present, counts
