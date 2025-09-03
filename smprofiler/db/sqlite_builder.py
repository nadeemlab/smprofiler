
import re
from importlib.resources import as_file
from importlib.resources import files
from contextlib import closing
from decimal import Decimal

from pandas import read_csv
from pandas import DataFrame
from networkx import MultiDiGraph
from networkx import topological_sort
from sqlite3 import connect
from sqlite3 import Cursor as SQLiteCursor
from psycopg import Cursor as PsycopgCursor
from attrs import define

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.verbose_sql_execution import _retrieve_script

@define
class EdgeData:
    foreign_table: str
    foreign_key: str
    name: str


class FindInsertOrder:
    @classmethod
    def get_safe_table_insert_order(cls, omittable_tables: tuple[str, ...]) -> tuple[str, ...]:
        G = cls._get_schema_graph(omittable_tables)
        return tuple(reversed(tuple(topological_sort(G))))

    @classmethod
    def _get_schema_graph(cls, omittable_tables: tuple[str, ...]) -> MultiDiGraph:
        G = MultiDiGraph()
        fields = cls._get_fields()
        for _, row in fields.iterrows():
            edge_data = cls._get_edge_data(row)
            n1 = cls._get_primary_table_handle(row)
            n2 = edge_data.foreign_table
            if n2 == '':
                continue
            if n1 in omittable_tables or n2 in omittable_tables:
                continue
            G.add_edge(
                n1,
                n2,
                name = edge_data.name,
                foreign_key = edge_data.foreign_key,
            )
        return G

    @classmethod
    def _get_fields(cls) -> DataFrame:
        with as_file(files('adiscstudies').joinpath('fields.tsv')) as path:
            fields = read_csv(path, sep='\t', keep_default_na=False)
        return fields

    @classmethod
    def _get_edge_data(cls, field_record) -> EdgeData:
        return EdgeData(field_record['Foreign table'], field_record['Foreign key'], field_record['Name'])

    @classmethod
    def _get_primary_table_handle(cls, field_record) -> str:
        return field_record['Table']


def _split_on_unquoted(string: str, delimiter: str, quote_characters: str) -> tuple[str, ...]:
    """
    Split a string on a delimiter, but only instances of the delimiter not escaped inside segments
    bounded by the quote characters.

    A somewhat naive implementation, but it works in many cases. Can be used to split a SQL script
    into statements by using delimiter ";" and quote character "'", assuming that the quote character
    is used in the normal way in matching pairs.
    """
    inside_quote = False
    start = 0
    tokens = []
    for i, c in enumerate(string):
        if c in quote_characters:
            inside_quote = not inside_quote
            continue
        if c == delimiter and not inside_quote:
            token = string[start:i]
            tokens.append(token)
            start = i + 1
    return tuple(tokens)


class SQLiteBuilder:
    """
    Creates a SQLite dump of the metadata elements (small data) of a given `scstudies` dataset
    located inside the application database.

    The full set of data elements includes:
    1. Large data: Everything that is per-cell or per-measurement, like expression values along cells.
       These tables tend to have millions or tens of millions of rows, ~10m.
    2. Medium-sized data: Computed features. These are numeric features at the per-sample granularity,
       but the combinatorial possibilities for features is very high, so this stratum of data grows
       as more computations accumulate. Total rows may number in the hundreds of thousands, ~100k.
    3. Small data: Everything else, all "metadata". This is the most complex stratum in terms of the
       schema, and the total number of records is in the thousands.

    The large data should probably never be included in a SQLite dump, as it would be in the tens of
    GB or more in size. In fact, eventually the large data will probably be file-based and hosted
    outside the SQL database anyway.

    The medium-sized data is generally acceptable for a SQLite dump, but perhaps sometimes unnecessary.
    So this class supports primarily exporting the small data, with the medium-sized data optionally.

    `no_feature_values` will omit the bulk of the computed feature data.
    `no_feature_specifications` will additionally omit even the definitions of the features that were
    computed.
    """
    connection: DBConnection
    include_feature_values: bool
    include_feature_specifications: bool
    feature_computation_tables = (
        'Quantitative feature value',
    )
    feature_specification_tables = (
        'Feature specification',
        'Feature specifier',
    )
    big_tables = (
        'Histological structure',
        'Shape file',
        'Histological structure identification',
        'Expression quantification',
    )

    def __init__(self, connection: DBConnection, no_feature_values: bool=False, no_feature_specifications: bool=False):
        self.connection = connection
        self.include_feature_values = not no_feature_values
        self.include_feature_specifications = not no_feature_specifications

    def get_dump(self, study: str) -> bytes:
        """
        This works as follows:
        The schema (table and field definitions) are written to the destination (sqlite database).
        The linked-table aspect of the schema is loaded as a directed graph.
        A topological sort order is determined for the tables.
        Records are copied from the source to the destination from the tables visited in
        this order, and foreign key dependencies for a given record will always be available since
        they will have been inserted already by the time that record is being copied.
        """
        with closing(connect(':memory:')) as db:
            with closing(db.cursor()) as cursor:
                self._infuse_schema(cursor)
                self._save_study(cursor, study)
            db.commit()
            serialization = db.serialize()
        return serialization

    def _infuse_schema(self, cursor: SQLiteCursor) -> None:
        schema = _retrieve_script(('schema.sql', ''), None, 'adiscstudies', quiet=True)
        for statement in _split_on_unquoted(schema, ';', "'"):
            statement = re.sub(r'^[\s\n]*COMMENT ON ', r'-- COMMENT ON ', statement)
            cursor.execute(f'{statement} ;')

    def _save_study(self, target: SQLiteCursor, study: str) -> None:
        tables = FindInsertOrder.get_safe_table_insert_order(self._omittable_tables())
        with DBCursor(connection=self.connection, study=study) as source:
            for table in tables:
                table_name = self._normalize(table)
                self._copy_records(source, target, table_name)

    def _omittable_tables(self) -> tuple[str, ...]:
        omittables = list(self.big_tables)
        if not self.include_feature_values:
            omittables.extend(list(self.feature_computation_tables))
        if not self.include_feature_specifications:
            omittables.extend(list(self.feature_specification_tables))
        return tuple(omittables)

    def _copy_records(self, source: PsycopgCursor, target: SQLiteCursor, table_name: str) -> None:
        query = f'SELECT * FROM {table_name};'
        source.execute(query)
        for row in source.fetchall():
            slots = ', '.join(['?'] * len(row))
            insert = f'INSERT INTO {table_name} VALUES ({slots});'
            target.execute(insert, self._clean_row(row))

    def _clean_row(self, row: tuple) -> tuple:
        return tuple(map(self._clean_entry, row))

    def _clean_entry(self, entry):
        if isinstance(entry, Decimal):
            return float(entry)
        return entry

    @staticmethod
    def _normalize(name):
        return re.sub(r'[ \-]', '_', name).lower()
