"""Drop a single study."""

from psycopg.errors import InvalidCatalogName

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class StudyDropper:
    """Drop a single study."""

    @staticmethod
    def drop(database_config_file: str | None, study: str) -> None:
        """ Use this method as the entrypoint into this class' functionality."""
        def matches_base_study(_study: str) -> bool:
            if _study == study:
                return True
            extract, _ = StudyCollectionNaming.strip_token(_study)
            if extract == study:
                return True
            return False

        file = database_config_file

        with DBCursor(database_config_file=file) as cursor:
            cursor.execute('SELECT schema_name, study FROM study_lookup ;')
            rows = cursor.fetchall()
            matches = tuple(filter(lambda row: matches_base_study(row[1]), rows))
            if len(matches) != 1:
                logger.warning('No schema (sense of postgres schema) found for study "%s".', study)
                return
            schema_name = matches[0][0]

        with DBConnection(file) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                try:
                    cursor.execute(f'DROP SCHEMA {schema_name} CASCADE;')
                    logger.info(f'Dropped schema: {schema_name}')
                except InvalidCatalogName:
                    logger.warning(f'The schema {schema_name} does not exist, can not drop it.')

        with DBCursor(database_config_file=file) as cursor:
            cursor.execute('DELETE FROM study_lookup WHERE schema_name=%s ;', (schema_name,))
            logger.info('Dropped record of schema (dataset) %s.', schema_name)
