"""
Copies all computed features for a study to a local file.
Useful for performance reasons in low-bandwidth contexts.
"""


from os.path import exists
from typing import cast

from pandas import read_sql_table
from pandas import read_csv
from pandas import DataFrame
from sqlalchemy import create_engine
from sqlalchemy import Connection as SQLAlchemyConnection

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.credentials import retrieve_credentials_from_file
from smprofiler.db.credentials import MissingKeysError 
from smprofiler.db.credentials import get_credentials_from_environment
from smprofiler.db.describe_features import get_handle
from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource


class SQLAlchemyWrapper(ChainableDestructableResource):
    connection: SQLAlchemyConnection

    def __init__(self, connection_str: str):
        engine = create_engine(connection_str)
        self.connection = engine.connect().__enter__()

    def get_connection(self) -> SQLAlchemyConnection:
        return self.connection

    def release(self) -> None:
        self.connection.__exit__(None, None, None)


class FeaturesCache(ChainableDestructableResource):
    filename: str
    schema: str
    connection: SQLAlchemyConnection

    def __init__(self, database_config_file: str | None, study: str):
        with DBCursor(database_config_file=database_config_file) as cursor:
            self.schema = cast(str, DBConnection.retrieve_study_schema(study, cursor))
        try:
            if not database_config_file:
                raise MissingKeysError(set())
            credentials = retrieve_credentials_from_file(database_config_file)
        except MissingKeysError:
            credentials = get_credentials_from_environment()
        connection_str = f'postgresql://{credentials.user}:{credentials.password}@{credentials.endpoint}/{credentials.database}'
        wrapper = SQLAlchemyWrapper(connection_str)
        self.add_subresource(SQLAlchemyWrapper(connection_str))
        self.filename = 'feature_cache.tsv'
        self.connection = wrapper.get_connection()

    def retrieve_features_cache(self):
        if self._exists():
            return self._retrieve_from_file()
        df = self._retrieve()
        self._write(df)
        return df

    def _exists(self):
        return exists(self.filename)

    def _retrieve_from_file(self) -> DataFrame:
        return read_csv(self.filename, sep='\t', keep_default_na=False)

    def _retrieve(self) -> DataFrame:
        schema = self.schema
        connection = self.connection
        feature_specifications = read_sql_table('feature_specification', connection, schema=schema)
        feature_specifiers = read_sql_table('feature_specifier', connection, schema=schema)
        quantitative_feature_values = read_sql_table('quantitative_feature_value', connection, schema=schema)
        ds = set(feature_specifications['derivation_method'])
        lookup = {d: get_handle(d) for d in ds}
        feature_specifications['feature_type'] = feature_specifications['derivation_method'].apply(lambda d: lookup[d])
        feature_specifications = feature_specifications[['identifier', 'feature_type']]
        feature_specifications = feature_specifications.rename(columns={'identifier': 'feature'}).set_index('feature')
        ordinalities = list(set(feature_specifiers['ordinality']))
        feature_specifiers = feature_specifiers.rename(columns={'feature_specification': 'feature'})
        feature_specifiers = feature_specifiers.pivot(
            index='feature', columns='ordinality', values='specifier'
        ).rename(columns={str(o): f'specifier{o}' for o in ordinalities})
        meta = feature_specifications.join(feature_specifiers)
        df = quantitative_feature_values.join(meta, on='feature')
        del df['identifier']
        mask = df['feature_type'] == 'gnn importance score'
        df = (df[~mask]).sort_values(by=['feature', 'subject'])
        df = df.rename(columns={'subject': 'sample'})
        return df

    def _write(self, df: DataFrame) -> None:
        df.to_csv(self.filename, sep='\t', index=False)


