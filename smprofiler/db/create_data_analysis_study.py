"""Functions to create, insert, and check for a data analysis study in the database."""
import re
import datetime
from typing import cast

from psycopg import connection as Connection

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class DataAnalysisStudyFactory:
    """Creates and retrieves custom data analysis studies in the database."""
    connection: Connection
    study: str
    specifier: str
    name: str | None

    def __init__(self, connection, study: str, specifier: str):
        self.connection = connection
        self.study = study
        self.specifier = specifier
        self._retrieve_existing_study()
        if self._already_exists():
            logger.warning('Data analysis study "%s" already exists.', self.name)

    def _retrieve_existing_study(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute('''
            SELECT das.name
            FROM data_analysis_study das
            JOIN study_component sc
                ON sc.component_study=das.name
            WHERE sc.primary_study=%s
        ;
        ''', (self.study,))
        names: list[str] = [row[0] for row in cursor.fetchall()]
        matches = [name for name in names if re.search(self.specifier, name)]
        if len(matches) > 0:
            self.name = matches[0]
        else:
            self.name = None

    def _already_exists(self):
        return self.name is not None

    def create(self) -> str:
        if self._already_exists():
            return cast(str, self.name)
        timestring = str(datetime.datetime.now())
        name = f'{self.study} : {self.specifier} : {timestring}'
        cursor = self.connection.cursor()
        cursor.execute('''
            INSERT INTO data_analysis_study(name)
            VALUES (%s) ;
        ''', (name,))
        cursor.execute('''
            INSERT INTO study_component(primary_study, component_study)
            VALUES (%s, %s) ;
        ''', (self.study, name))
        cursor.close()
        self.connection.commit()
        logger.info('Inserted data analysis study: "%s"', name)
        return name
