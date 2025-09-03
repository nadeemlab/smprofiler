"""
Utility to drop or recreate certain constraints in the single-cell ADI SQL schema. Used to boost
performance of certain operations.
"""
from enum import Enum
from enum import auto
from importlib.resources import as_file
from importlib.resources import files
import re

import pandas as pd

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import retrieve_study_names

from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger(__name__)


class DBConstraintsToggling(Enum):
    """Request type for modification of the DB constraints."""
    RECREATE = auto()
    DROP = auto()


def is_table_for_dropping(table, all_tables=False):
    if all_tables:
        return True
    return table in big_tables()


def all_tables_list():
    with as_file(files('adiscstudies').joinpath('fields.tsv')) as path:
        fields = pd.read_csv(path, sep='\t', na_filter=False)
    tables = sorted(list(set(list(fields['Table']))))
    return [normalize(t) for t in tables]


def big_tables():
    return [
        'histological_structure',
        'histological_structure_identification',
        'expression_quantification',
        'shape_file',
    ]


def normalize(name):
    return re.sub(r'[ \-]', '_', name).lower()


def get_constraint_status(cursor, all_tables=False):
    if all_tables:
        droppable_tables = all_tables_list()
    else:
        droppable_tables = big_tables()
    query = f'''
    SELECT DISTINCT
        pg_constraint.contype as connection_type,
        pg_constraint.conname as constraint_name,
        pg_class.relname as relation_name
    FROM pg_trigger
    JOIN pg_class ON pg_trigger.tgrelid = pg_class.oid
    JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace 
    JOIN pg_constraint ON pg_constraint.oid = pg_trigger.tgconstraint
    WHERE relname IN {str(tuple(droppable_tables))}
    ORDER BY relation_name, constraint_name;
    '''
    cursor.execute(query)
    column_names = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return [column_names, rows]


def get_constraint_design(all_tables=False):
    with as_file(files('adiscstudies').joinpath('fields.tsv')) as path:
        fields = pd.read_csv(path, sep='\t', na_filter=False)
    foreign_key_constraints = [
        [normalize(str(s)) for s in [row['Table'], row['Name'],
                                     row['Foreign table'], row['Foreign key'], row['Ordinality']]]
        for i, row in fields.iterrows()
        if row['Foreign table'] != '' and row['Foreign key'] != ''
            and is_table_for_dropping(normalize(row['Table']), all_tables=all_tables)
    ]
    return foreign_key_constraints


def print_constraint_status(column_names, info_rows):
    def print_formatted(row):
        return print(f"{row[0]:<16} {row[1]:<65} {row[2]:<40}")
    logger.info('Printing constraint info.')
    print_formatted(column_names)
    for row in info_rows:
        print_formatted(row)


def toggle_constraints_cursor(cursor, state: DBConstraintsToggling, all_tables: bool=False) -> None:
    try:
        if state == DBConstraintsToggling.RECREATE:
            pattern = '''
            ALTER TABLE %s 
            ADD CONSTRAINT %s 
            FOREIGN KEY (%s) 
            REFERENCES %s (%s)
            ON DELETE CASCADE ;'''
            for tablename, field_name, foreign_tablename, foreign_field_name, ordinality \
                    in get_constraint_design(all_tables=all_tables):
                statement = pattern % (
                    tablename,
                    f'{tablename}{ordinality}',
                    field_name,
                    foreign_tablename,
                    foreign_field_name,
                )
                logger.debug('Executing: %s', statement)
                cursor.execute(statement)
            status = get_constraint_status(cursor, all_tables=all_tables)
            print_constraint_status(*status)

        if state == DBConstraintsToggling.DROP:
            pattern = '''
            ALTER TABLE %s
            DROP CONSTRAINT IF EXISTS %s;'''
            status = get_constraint_status(cursor, all_tables=all_tables)
            print_constraint_status(*status)
            for _, constraint_name, tablename in status[1]:
                statement = pattern % (tablename, constraint_name)
                logger.debug('Executing: %s', statement)
                cursor.execute(statement)
    except Exception as exception:
        cursor.close()
        raise exception


def toggle_constraints(
    database_config_file: str | None,
    study: str,
    state: DBConstraintsToggling = DBConstraintsToggling.RECREATE,
    all_tables: bool = False,
):
    studies = retrieve_study_names(database_config_file)
    if not study in studies:
        logger.warning('Study named "%s" not in database.', study)
        return

    with DBCursor(database_config_file=database_config_file, study=study) as cursor:
        toggle_constraints_cursor(cursor, state, all_tables=all_tables)
