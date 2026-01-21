
import re
from os.path import join
from os.path import exists
import importlib.resources

from pandas import read_csv
from psycopg import Connection as PsycopgConnection

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger(__name__)


def transcribe_permanent_event_metadata(file_path: str, connection: PsycopgConnection | None, database_config_file: str | None) -> None:
    """
    Copies file-serialized TSV tables into the database at the given cursor, assuming
    that the schema of both tables follows the adiscstudies package.
    """
    if connection is None:
        study_name = _retrieve_study_name(file_path)
        with DBConnection(database_config_file=database_config_file, study=study_name) as connection:
            _transcribe_to_connection(file_path, connection)
    else:
        _transcribe_to_connection(file_path, connection)

def _transcribe_to_connection(file_path, connection: PsycopgConnection) -> None:
    tables = ('permanent_condition_diagnosis.tsv', 'condition_lack.tsv')
    for table in tables:
        _transcribe(file_path, table, connection)

def _transcribe(file_path: str, tablefile: str, connection: PsycopgConnection) -> None:
    filename = join(file_path, tablefile)
    if not exists(filename):
        logger.warning(f'Source file does not exist: {filename}')
        return
    df = read_csv(filename, sep='\t')
    tablename = re.sub(r'\.tsv$', '', tablefile)
    columns = _get_columns(tablename)
    df.columns = list(map(_normalize_column, list(df.columns)))
    if columns != tuple(df.columns):
        raise ValueError(f'Schema for supplied table (columns: {df.columns}) does not match: {columns}')
    with connection.cursor() as cursor:
        for _, row in df.iterrows():
            values = tuple(row[c] for c in columns)
            template = '(' + ', '.join(['?']*len(columns)) + ')'
            query = f'INSERT INTO {tablename} VALUES {template} ;'
            cursor.execute(query, values)
    connection.commit()

def _normalize_column(c: str) -> str:
    return re.sub(' ', '_', c).lower()

def _get_columns(table: str) -> tuple[str, ...]:
    with importlib.resources.path('adiscstudies', 'fields.tsv') as path:
        fields = read_csv(path, sep='\t')
    return tuple(map(_normalize_column, list(fields[fields['Table'].apply(_normalize_column) == table]['Label'])))

def _retrieve_study_name(file_path: str) -> str:
    return StudyCollectionNaming.extract_study_from_file(join(file_path, 'study.json'))


