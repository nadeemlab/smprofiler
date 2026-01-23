
import re
from os.path import join
import importlib.resources

from pandas import read_csv
from pandas import DataFrame
from psycopg import Connection as PsycopgConnection

from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger(__name__)


class TableTranscriber:
    """
    Copies file-serialized TSV tables into the database at the given connection,
    assuming that the schema of both tables follows the adiscstudies package.
    """
    table_files: tuple[str, ...]
    connection: PsycopgConnection

    def __init__(self, table_files: tuple[str, ...], connection: PsycopgConnection):
        self.table_files = table_files
        self.connection = connection

    def transcribe(self) -> None:
        for table_file in self.table_files:
            self._transcribe_table(table_file)

    def _transcribe_table(self, table_file: str) -> None:
        df = read_csv(table_file, sep='\t')
        logger.info(f'Considering {table_file}: {df}')
        table_name = re.sub(r'\.tsv$', '', table_file)
        df.columns = list(map(_normalize_column, list(df.columns)))
        self._validate_schema(df, table_name)
        columns = _get_columns(table_name)
        with self.connection.cursor() as cursor:
            for _, row in df.iterrows():
                values = tuple(str(row[c]) for c in columns)
                where = f'WHERE NOT EXISTS ( SELECT * FROM {table_name} t WHERE ' + ' AND '.join(f"t.{c}='{v}'" for c, v in zip(columns, values)) + ' )'
                fields = ', '.join(columns)
                vs = ', '.join(f"'{v}'" for v in values)
                query = f'INSERT INTO {table_name} ({fields}) SELECT {vs} {where} ;'
                logger.info(f'Inserting {table_name} record: {query}')
                cursor.execute(query)
        self.connection.commit()

    def _validate_schema(self, df: DataFrame, table_name: str) -> None:
        columns = _get_columns(table_name)
        if columns != tuple(df.columns):
            raise ValueError(f'Schema for supplied table (columns: {df.columns}) does not match: {columns}')

def get_permanent_events_transcriber(file_path: str, connection: PsycopgConnection) -> TableTranscriber:
    tables = ('permanent_condition_diagnosis.tsv', 'condition_lack.tsv', 'diagnosis.tsv')
    table_files = tuple(map(lambda t: join(file_path, t), tables))
    return TableTranscriber(table_files, connection)

def _normalize_column(c: str) -> str:
    return re.sub(' ', '_', c).lower()

def _get_columns(table: str) -> tuple[str, ...]:
    with importlib.resources.path('adiscstudies', 'fields.tsv') as path:
        fields = read_csv(path, sep='\t')
    return tuple(map(_normalize_column, list(fields[fields['Table'].apply(_normalize_column) == table]['Label'])))


