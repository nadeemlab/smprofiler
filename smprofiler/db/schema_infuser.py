""" Utility to write the single-cell studies "ADI" SQL schema, plus performance- and SMProfiler-related
tweaks, into a Postgresql instance.
"""
from importlib.resources import as_file
from importlib.resources import files
import re

import pandas as pd  # type: ignore
from psycopg import Error as PsycopgError
from psycopg.errors import UndefinedTable
from psycopg.errors import DuplicateTable

from smprofiler.db.database_connection import ensure_main_database_created
from smprofiler.db.database_connection import create_common_area
from smprofiler.db.credentials import metaschema_schema
from smprofiler.db.verbose_sql_execution import verbose_sql_execute
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class SchemaInfuser:
    """Create single cell database schema in a given database."""
    database_config_file: str | None
    study: str | None

    def __init__(self, database_config_file: str | None = None, study: str | None = None):
        self.database_config_file = database_config_file
        self.study = study

    def setup_lightweight_metaschema(self, force=False):
        ensure_main_database_created(self.database_config_file)
        create_common_area(self.database_config_file, metaschema_schema())
        if force:
            try:
                self._verbose_sql_execute(('drop_metaschema.sql', 'drop metaschema tables'))
            except UndefinedTable:
                pass
        try:
            self._verbose_sql_execute(
                ('metaschema.sql', 'create tables from lightweight metaschema'),
                verbosity='itemize',
            )
        except DuplicateTable:
            logger.info('Metaschema table already exists.')

        try:
            self._verbose_sql_execute(('grant_on_tables.sql', 'grant appropriate access to users'))
        except PsycopgError as exception:
            logger.warning('Could not run grant privileges script. Possibly users are not set up.')
            logger.warning(exception)

    def setup_schema(self, force=False):
        message = 'This creation tool assumes that the database server itself and users are already setup.'
        logger.info(message)
        if force:
            self._verbose_sql_execute(
                (None, 'drop tables from main schema'),
                contents=self.create_drop_tables(),
            )
        logger.info('Executing schema.sql contents.')
        self._verbose_sql_execute(
            ('schema.sql', 'create tables from main schema'),
            source_package='adiscstudies',
            verbosity='silent',
        )
        self._verbose_sql_execute(('performance_tweaks.sql', 'tweak main schema'))
        try:
            self._verbose_sql_execute(('grant_on_tables.sql', 'grant appropriate access to users'))
        except PsycopgError as exception:
            logger.warning('Could not run grant privileges script. Possibly users are not set up.')
            logger.warning(exception)

    def normalize(self, name):
        return re.sub(r'[ \-]', '_', name).lower()

    def get_schema_documentation_tables(self):
        return [
            f'reference_{tablename}'
            for tablename in ['tables', 'fields', 'entities', 'properties', 'values']
        ]

    def create_drop_tables(self):
        with as_file(files('adiscstudies').joinpath('fields.tsv')) as path:
            fields = pd.read_csv(path, sep='\t', keep_default_na=False)
        table_names = sorted(list(set(self.normalize(t) for t in fields['Table'])))
        performance_extras = ['sample_strata', 'quantitative_feature_value_queue', 'umap_plots']
        table_names = table_names + self.get_schema_documentation_tables() + performance_extras
        return '\n'.join([
            f'DROP TABLE IF EXISTS {t} CASCADE ; ' for t in table_names
        ])

    def _verbose_sql_execute(self,
        filename_description,
        source_package='smprofiler.db.data_model',
        contents: str | None = None,
        **kwargs,
    ):
        verbose_sql_execute(
            filename_description,
            self.database_config_file,
            source_package=source_package,
            contents=contents,
            study=self.study,
            **kwargs,
        )
