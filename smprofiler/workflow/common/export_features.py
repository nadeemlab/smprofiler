"""Convenience uploader of feature data into SMProfiler database tables that comprise a sparse
representation of the features. Abstracts (wraps) the actual SQL queries.
"""

from hashlib import sha256
from importlib.resources import as_file
from importlib.resources import files
from itertools import product
import re

import pandas as pd  # type: ignore
from psycopg import Connection as PsycopgConnection
from psycopg import Cursor as PsycopgCursor
from psycopg.errors import UniqueViolation

from smprofiler.db.describe_features import get_handle
from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.db.database_connection import ConnectionProvider
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class ADIFeaturesUploader(SourceToADIParser):
    """
    Upload sparse representation of feature values to tables quantitative_feature_value,
    feature_specification, feature_specifier.
    """
    connection_provider: ConnectionProvider
    feature_values: list[tuple[tuple[str, ...], str , float | None]]

    def __init__(self,
        connection: PsycopgConnection,
        data_analysis_study: str,
        derivation_and_number_specifiers,
        impute_zeros: bool = False,
        **kwargs,
    ):
        derivation_method, specifier_number = derivation_and_number_specifiers
        self.impute_zeros = impute_zeros
        with as_file(files('adiscstudies').joinpath('fields.tsv')) as path:
            fields = pd.read_csv(path, sep='\t', na_filter=False)
        SourceToADIParser.__init__(self, fields)
        args = (data_analysis_study, derivation_method, specifier_number)
        self.record_feature_specification_template(*args)
        self.connection_provider = ConnectionProvider(connection)

    def record_feature_specification_template(self,
        data_analysis_study,
        derivation_method,
        specifier_number,
    ):
        self.data_analysis_study = data_analysis_study
        self.derivation_method = derivation_method
        self.specifier_number = specifier_number
        self.insert_queries = {
            tablename: self.generate_basic_insert_query(tablename)
            for tablename in
            ['feature_specification', 'feature_specifier', 'quantitative_feature_value']
        }
        self.feature_values = []

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if self.connection_provider.is_connected():
            self.upload()

    def stage_feature_value(self, specifiers: tuple[str, ...], subject: str, value: float | None):
        self.validate_specifiers(specifiers)
        self.feature_values.append((specifiers, subject, value))

    def validate_specifiers(self, specifiers):
        if len(specifiers) != self.specifier_number:
            message = \
                f'Feature specified by "{specifiers}", but should only have ' \
                f'{self.specifier_number} specifiers.'
            logger.error(message)
            raise ValueError(message)

    def get_connection(self):
        return self.connection_provider.get_connection()

    def upload(self) -> None:
        if self.check_nothing_to_upload():
            return
        self.test_subject_existence()
        self.test_study_existence()
        if self.impute_zeros:
            self.add_imputed_zero_values()
        connection = self.get_connection()
        connection.commit()
        connection._set_autocommit(True)
        cursor = connection.cursor()
        specifiers_list = sorted(list(set(row[0] for row in self.feature_values)))
        insert_notice = 'Inserting feature "%s" for study "%s".'
        logger.info(insert_notice, self.derivation_method, self.data_analysis_study)
        for specifiers in specifiers_list:
            get_or_create = ADIFeaturesUploader._get_or_create_generic_feature_specification
            feature_identifier, is_new = get_or_create(
                cursor, self.data_analysis_study, specifiers, self.derivation_method
            )
            feature_values = map(
                lambda row: (row[1], row[2]),
                filter(lambda row: row[0] == specifiers, self.feature_values),
            )
            self.insert_feature_values(cursor, feature_identifier, feature_values)
        connection.commit()
        cursor.close()

    def check_nothing_to_upload(self):
        if len(self.feature_values) == 0:
            logger.info('No feature values given to be uploaded.')
            return True
        return False

    def test_subject_existence(self):
        subject_ids = self.get_subject_identifiers()
        unknown_subjects = set(row[1] for row in self.feature_values).difference(subject_ids)
        number_unknown = len(unknown_subjects)
        if number_unknown > 0:
            unknowns_message = 'Feature values refer to %s unknown subjects: %s'
            subset = list(unknown_subjects)[0:min(10, len(unknown_subjects))]
            logger.warning(unknowns_message, number_unknown, subset)
        else:
            logger.info('All feature value subjects were known "subjects" or "specimens".')

    def get_subject_identifiers(self):
        cursor = self.get_connection().cursor()
        cursor.execute('SELECT identifier FROM subject;')
        rows = cursor.fetchall()
        subject_ids = [row[0] for row in rows]
        cursor.execute('SELECT specimen FROM specimen_collection_process;')
        rows = cursor.fetchall()
        specimen_ids = [row[0] for row in rows]
        cursor.close()
        return subject_ids + specimen_ids

    def test_study_existence(self):
        cursor = self.get_connection().cursor()
        cursor.execute('SELECT name FROM data_analysis_study;')
        rows = cursor.fetchall()
        names = [row[0] for row in rows]
        cursor.close()
        if not self.data_analysis_study in names:
            message = f'Data analysis study "{self.data_analysis_study}" does not exist.'
            logger.error(message)
            raise ValueError(message)

    def coordinate_set(self, tuples, coordinate):
        return sorted(list(set(t[coordinate] for t in tuples)))

    def add_imputed_zero_values(self):
        support = [(specifiers, subject) for specifiers, subject, value in self.feature_values]
        known_specifications = self.coordinate_set(support, 0)
        known_subjects = self.coordinate_set(support, 1)
        no_value_cases = []
        for case in product(known_specifications, known_subjects):
            if case not in support:
                no_value_cases.append(case)
        logger.info('Imputed %s zero-value assignments.', len(no_value_cases))
        assignments = [(case[0], case[1], 0) for case in no_value_cases]
        self.feature_values = self.feature_values + assignments

    def insert_feature_values(self, cursor: PsycopgCursor, feature_identifier, feature_values):
        for subject, value in feature_values:
            cursor.execute(
                self.insert_queries['quantitative_feature_value'],
                (feature_identifier, subject, value),
            )

    @classmethod
    def _get_or_create_generic_feature_specification(
        cls,
        cursor: PsycopgCursor,
        data_analysis_study: str,
        specifiers: tuple[str, ...],
        derivation_method: str,
    ) -> tuple[str, bool]:
        specification = cls._get_feature_specification(cursor, specifiers, derivation_method)
        if specification is not None:
            return (specification, False)
        specification = cls._create_feature_specification(
            cursor, data_analysis_study, specifiers, derivation_method,
        )
        return (specification, True)

    @classmethod
    def _get_feature_specification(cls,
        cursor: PsycopgCursor,
        specifiers: tuple[str, ...],
        derivation_method: str,
    ) -> str | None:
        args = (
            *specifiers,
            derivation_method,
        )
        specifiers_portion = ' AND '.join(
            f"( fs.specifier=%s AND fs.ordinality='{i+1}')"
            for i in range(len(specifiers))
        )
        query = f'''
        SELECT
            fsn.identifier,
            fs.specifier
        FROM feature_specification fsn
        JOIN feature_specifier fs ON fs.feature_specification=fsn.identifier
        WHERE {specifiers_portion} AND fsn.derivation_method=%s
        ;
        '''
        cursor.execute(query, args)
        rows = tuple(cursor.fetchall())
        feature_specifications: dict[str, list[str]] = {row[0]: [] for row in rows}
        matches_list: list[str] = []
        for row in rows:
            feature_specifications[row[0]].append(row[1])
        for key, _specifiers in feature_specifications.items():
            if len(_specifiers) == len(specifiers):
                matches_list.append(key)
        matches = tuple(matches_list)
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            text = 'Multiple features match the selected specification'
            message = f'{text}: {matches} {specifiers}'
            logger.warning(message)
        return matches[0]

    @classmethod
    def _create_feature_specification(cls,
        cursor: PsycopgCursor,
        data_analysis_study: str,
        specifiers: tuple[str, ...],
        derivation_method: str,
    ) -> str:
        feature_specification = ADIFeatureSpecificationUploader.add_new_feature(
            specifiers, derivation_method, data_analysis_study, cursor,
        )
        return feature_specification


class ADIFeatureSpecificationUploader:
    """Just upload a new feature specification."""
    @classmethod
    def add_new_feature(cls, specifiers, derivation_method, data_analysis_study, cursor: PsycopgCursor, appendix: str | None = None):
        cursor.execute('BEGIN;')
        identifier, is_new = cls.insert_hash(derivation_method, specifiers, cursor, appendix=appendix)
        if is_new:
            cls.insert_specification(str(identifier), derivation_method, data_analysis_study, cursor)
            cls.insert_specifiers(identifier, specifiers, cursor)
            cursor.execute('COMMIT;')
        return identifier

    @classmethod
    def ondemand_descriptor(cls):
        return 'ondemand computed features'

    @classmethod
    def get_data_analysis_study(cls, measurement_study, cursor: PsycopgCursor):
        cursor.execute('''
        SELECT sc.primary_study FROM study_component sc
        WHERE sc.component_study=%s ;
        ''', (measurement_study,))
        study = tuple(cursor.fetchall())[0][0]

        cursor.execute('''
        SELECT das.name
        FROM data_analysis_study das
        JOIN study_component sc ON sc.component_study=das.name
        WHERE sc.primary_study=%s ;
        ''', (study,))
        rows = cursor.fetchall()
        ondemand = cls.ondemand_descriptor()
        names = sorted([row[0] for row in rows if re.search(f'{ondemand}', row[0])])
        if len(names) >= 1:
            return names[0]
        data_analysis_study = cls.form_ondemand_study_name(study)
        cursor.execute('''
        INSERT INTO data_analysis_study (name) VALUES (%s) ON CONFLICT DO NOTHING;
        ''', (data_analysis_study,))
        cursor.execute('''
        INSERT INTO study_component (primary_study, component_study) VALUES (%s , %s) ON CONFLICT DO NOTHING;
        ''', (study, data_analysis_study))
        return data_analysis_study

    @classmethod
    def form_ondemand_study_name(cls, study: str) -> str:
        ondemand = cls.ondemand_descriptor()
        return f'{study} - {ondemand}'

    @classmethod
    def insert_specification(
        cls, specification: str, derivation_method: str, data_analysis_study: str, cursor: PsycopgCursor,
    ):
        handle = get_handle(derivation_method)
        query = '''
        INSERT INTO feature_specification (identifier, derivation_method, study) VALUES (%s, %s, %s);
        '''
        cursor.execute(query, (specification, derivation_method, data_analysis_study))

    @classmethod
    def insert_specifiers(cls, specification: int, specifiers: tuple, cursor: PsycopgCursor):
        many = [(specification, specifier, str(i+1)) for i, specifier in enumerate(specifiers)]
        logger.debug(f'Inserting specifiers ({specification}): {specifiers}')
        cursor.executemany(
            '''
            INSERT INTO feature_specifier (feature_specification, specifier, ordinality) VALUES (%s, %s, %s) ;
            ''',
            many,
        )

    @classmethod
    def insert_hash(cls, derivation_method: str, specifiers: tuple, cursor: PsycopgCursor, appendix: str | None=None) -> tuple[int, bool]:
        hash_identity = cls._generate_hash(tuple([derivation_method] + list(specifiers) + ([appendix] if appendix else [])))
        try:
            cursor.execute(
                '''
                INSERT INTO
                    feature_hash(feature, hash_identity)
                VALUES
                    (nextval(pg_get_serial_sequence('feature_hash', 'feature')), %s)
                RETURNING feature
                ;
                ''',
                (hash_identity,),
            )
            feature = tuple(cursor.fetchall())[0][0]
            logger.debug(f'Created new feature: {feature}')
            return (feature, True)
        except UniqueViolation:
            cursor.execute('COMMIT;')
            cursor.execute('SELECT feature FROM feature_hash WHERE hash_identity=%s;', (hash_identity,))
            feature = tuple(cursor.fetchall())[0][0]
            logger.debug(f'Feature already exists: {feature}')
            return (feature, False)

    @classmethod
    def _generate_hash(cls, specifiers: tuple) -> str:
        h = sha256()
        h.update(str.encode(f'{specifiers}'))
        return h.hexdigest()
