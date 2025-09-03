"""Source file parsing for overall study/project metadata."""
import json

from psycopg import cursor as PsycopgCursor

from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class StudyParser(SourceToADIParser):
    """Parse source files containing study-level metadata."""

    def _cautious_insert(self, tablename, record, cursor: PsycopgCursor, no_primary=True):
        was_found, _ = self.check_exists(tablename, record, cursor, no_primary=no_primary)
        if was_found:
            logger.debug('"%s" %s already exists.', tablename, str(record))
        else:
            cursor.execute(self.generate_basic_insert_query(tablename), record)

    def _insert_study_components(self, study_name: str, cursor: PsycopgCursor) -> None:
        collection = SourceToADIParser.get_measurement_study_name(study_name)
        measurement = SourceToADIParser.get_collection_study_name(study_name)
        data_analysis = SourceToADIParser.get_data_analysis_study_name(study_name)
        for substudy in [collection, measurement, data_analysis]:
            record = [study_name, substudy]
            self._cautious_insert('study_component', record, cursor)

    def parse(self, connection, study_file) -> str:
        with open(study_file, 'rt', encoding='utf-8') as file:
            study = json.loads(file.read())
        study_name = StudyCollectionNaming.extract_study_from_file(study_file)

        cursor = connection.cursor()

        record: tuple[str, ...] = (study_name, study['Institution'])
        self._cautious_insert('study', record, cursor)

        for person in study['People']:
            keys = ['Full name', 'Surname', 'Given name', 'ORCID']
            record = tuple(person[key] for key in keys)
            self._cautious_insert('research_professional', record, cursor)

        record = (
            study['Study contact person']['Name'],
            study_name,
            study['Study contact person']['Contact reference'],
        )
        self._cautious_insert('study_contact_person', record, cursor)

        self._insert_study_components(study_name, cursor)

        for publication in study['Publications']:
            record = (
                publication['Title'],
                study_name,
                publication['Document type'],
                publication['Publisher'],
                publication['Date'],
                publication['URL'],
            )
            self._cautious_insert('publication', record, cursor)

        for publication in study['Publications']:
            for ordinality, author in enumerate(publication['Authors']):
                record = (
                    author,
                    publication['Title'],
                    str(ordinality),
                )
                self._cautious_insert('author', record, cursor)

        logger.info('Parsed records for study "%s".', study_name)
        connection.commit()
        cursor.close()
        return study_name
