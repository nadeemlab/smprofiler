
import re
from os.path import join
import importlib.resources
from importlib.resources import as_file
from importlib.resources import files

from pandas import read_csv
from pandas import DataFrame
from psycopg import Connection as PsycopgConnection

from smprofiler.workflow.tabular_import.parsing.diagnosis import DiagnosisParser
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
        table_name = re.search(r'([^/]+)\.tsv$', table_file).group(1)
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
            raise ValueError(f'Schema for supplied table (columns: {df.columns}) does not match "{table_name}": {columns}')


class SurvivalDataTranscriber:
    file_path: str
    connection: PsycopgConnection
    t: TableTranscriber

    def __init__(self, file_path: str, connection: PsycopgConnection):
        tables = ('permanent_condition_diagnosis.tsv', 'condition_lack.tsv')
        table_files = tuple(map(lambda t: join(file_path, t), tables))
        self.file_path = file_path
        self.connection = connection
        self.t = TableTranscriber(table_files, connection)

    def transcribe(self) -> None:
        self.t.transcribe()
        diagnosis_file = join(self.file_path, 'diagnosis.tsv')
        DiagnosisParser(get_fields()).parse(self.connection, diagnosis_file, drop_first=True)


def get_permanent_events_transcriber(file_path: str, connection: PsycopgConnection) -> SurvivalDataTranscriber:
    return SurvivalDataTranscriber(file_path, connection)

def _normalize_column(c: str) -> str:
    return re.sub(' ', '_', c).lower()

def _get_columns(table: str) -> tuple[str, ...]:
    fields = get_fields()
    return tuple(map(_normalize_column, list(fields[fields['Table'].apply(_normalize_column) == table]['Label'])))

def get_fields():
    with importlib.resources.path('adiscstudies', 'fields.tsv') as path:
        fields = read_csv(path, sep='\t')
    return fields
 
