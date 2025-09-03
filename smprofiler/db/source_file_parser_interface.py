"""
Interface (and common functionality) for classes whose concrete implementations
are meant to be parsers of some specific source file into the 'single cell
studies ADI' schema.
"""
import re

import psycopg

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class SourceToADIParser:
    """Interface for specific source file parsing into single cell schema."""
    def __init__(self, fields, **kwargs):  # pylint: disable=unused-argument
        self.fields_from_source = fields

    def get_fields(self):
        return self.fields_from_source

    @staticmethod
    def get_collection_study_name(study_name):
        return study_name + " - specimen collection"

    @staticmethod
    def get_measurement_study_name(study_name):
        return study_name + " - measurement"

    @staticmethod
    def get_data_analysis_study_name(study_name):
        return study_name + " - data analysis"

    def get_placeholder(self):
        placeholder = '%s'
        return placeholder

    def normalize(self, string):
        string = re.sub(r'[ \-]', '_', string)
        string = string.lower()
        return string

    def get_field_names(self, tablename):
        fields = [
            field
            for i, field in self.get_fields().iterrows()
            if self.normalize(field['Table']) == self.normalize(tablename)
        ]
        fields_sorted = sorted(fields, key=lambda field: int(field['Ordinality']))
        fields_sorted = [f['Name'] for f in fields_sorted]
        return fields_sorted

    def generate_basic_insert_query(self, tablename):
        fields_sorted = self.get_field_names(tablename)
        if tablename in ('quantitative_feature_value', 'feature_specification'):
            fields_sorted = fields_sorted[1:]
        handle_duplicates = 'ON CONFLICT DO NOTHING '
        query = (
            'INSERT INTO ' + tablename + ' (' + ', '.join(fields_sorted) + ') '
            'VALUES (' + ', '.join([self.get_placeholder()]
                                   * len(fields_sorted)) + ') '
            + handle_duplicates + ' ;'
        )
        return query

    @staticmethod
    def is_integer(i):
        if isinstance(i, int):
            return True
        if re.match('^[0-9][0-9]*$', i):
            return True
        return False

    @staticmethod
    def get_next_integer_identifier(tablename, cursor, key_name='identifier'):
        cursor.execute(f'SELECT {key_name} FROM {tablename};')
        try:
            identifiers = cursor.fetchall()
        except psycopg.ProgrammingError:
            return 0
        known_integer_identifiers = [
            int(i[0]) for i in identifiers if SourceToADIParser.is_integer(i[0])]
        if len(known_integer_identifiers) == 0:
            return 0
        return max(known_integer_identifiers) + 1

    def check_exists(self, tablename, record, cursor, no_primary=False):
        """Assumes that the first entry in records is a fiat identifier, omitted for
        the purpose of checking pre-existence of the record.

        Returns pair:
        - was_found (bool)
        - key

        If no_primary = True, no fiat identifier column is assumed at all, and a key
        value of None is returned.
        """
        fields = self.get_field_names(tablename)
        primary = fields[0]
        if no_primary:
            primary = 'COUNT(*)'
            identifying_record = record
            identifying_fields = fields
        else:
            identifying_record = record[1:]
            identifying_fields = fields[1:]
        query = f'''
        SELECT {primary} FROM {tablename} WHERE {
            ' AND '.join(
                [
                    f'{field}={self.get_placeholder()} '
                    for field in identifying_fields
                ]
        )
        } ;
        '''
        cursor.execute(query, tuple(identifying_record))
        if not no_primary:
            rows = cursor.fetchall()
            if len(rows) == 0:
                return [False, None]
            if len(rows) > 1:
                logger.warning('"%s" contains duplicates records.', tablename)
            key = rows[0][0]
            return [True, key]
        count = cursor.fetchall()[0][0]
        if count == 0:
            return [False, None]
        return [True, None]
