"""Convenience accessors of study-related small data / metadata."""

from typing import cast
import re

from psycopg.errors import UndefinedTable

from smprofiler.db.simple_method_cache import simple_instance_method_cache
from smprofiler.workflow.common.export_features import ADIFeatureSpecificationUploader
from smprofiler.db.exchange_data_formats.study import (
    StudyContact,
    DataRelease,
    Publication,
    Institution,
    Assay,
    CountsSummary,
    StudyComponents,
    StudyHandle,
    StudySummary,
    Context,
    Products,
)
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.db.exchange_data_formats.metrics import AvailableGNN
from smprofiler.db.simple_query_patterns import GetSingleResult
from smprofiler.db.cohorts import get_sample_cohorts
from smprofiler.db.database_connection import SimpleReadOnlyProvider
from smprofiler.db.describe_features import get_feature_description
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class StudyAccess(SimpleReadOnlyProvider):
    """Provide study-related metadata."""

    @simple_instance_method_cache(log=True)
    def get_study_summary(self, study: str) -> StudySummary:
        components = self.get_study_components(study)
        counts_summary = self._get_counts_summary(components)
        contact = self._get_contact(study)
        institution = self._get_institution(study)
        data_release = self._get_data_release(study)
        publication = self._get_publication(study)
        assay = self._get_assay(components.measurement)
        sample_cohorts = get_sample_cohorts(self.cursor, study)
        findings = self.get_study_findings()
        has_umap = self.has_umap()
        has_intensities = self.has_intensities()
        curation_notes = self.get_curation_notes()
        return StudySummary(
            context=Context(institution=institution, assay=assay, contact=contact),
            products=Products(data_release=data_release, publication=publication),
            counts=counts_summary,
            cohorts=sample_cohorts,
            findings=findings,
            has_umap=has_umap,
            has_intensities=has_intensities,
            curation_notes=curation_notes,
        )

    def get_study_components(self, study: str) -> StudyComponents:
        substudy_tables = {
            'collection': 'specimen_collection_study',
            'measurement': 'specimen_measurement_study',
            'analysis': 'data_analysis_study',
        }
        substudies = {}
        for key, tablename in substudy_tables.items():
            self.cursor.execute(f'''
            SELECT ss.name FROM {tablename} ss
            JOIN study_component sc ON sc.component_study=ss.name
            WHERE sc.primary_study=%s
            ;
            ''', (study,))
            name = [
                row[0] for row in self.cursor.fetchall()
                if not self._is_secondary_substudy(row[0])
            ][0]
            substudies[key] = name
        return StudyComponents(**substudies)

    def get_available_gnn(self, study: str) -> AvailableGNN:
        feature_class = get_feature_description("gnn importance score")
        self.cursor.execute('''
        SELECT fsp.specifier
        FROM feature_specification fs
        JOIN feature_specifier fsp ON fs.identifier=fsp.feature_specification
        JOIN study_component sc ON sc.component_study=fs.study
        WHERE sc.primary_study=%s AND fs.derivation_method=%s AND fsp.ordinality='1';
        ''', (study, feature_class))
        rows = tuple(self.cursor.fetchall())
        return AvailableGNN(plugins=tuple(specifier for (specifier, ) in rows))

    def get_study_findings(self) -> list[str]:
        return self._get_study_small_artifacts('findings')

    def get_study_gnn_plot_configurations(self) -> list[str]:
        return self._get_study_small_artifacts('gnn_plot_configurations')

    def _get_study_small_artifacts(self, name: str) -> list[str]:
        self.cursor.execute(f'SELECT txt FROM {name} ORDER BY id;')
        return [row[0] for row in self.cursor.fetchall()]

    @staticmethod
    def _is_secondary_substudy(substudy: str) -> bool:
        is_fractions = bool(re.search('phenotype fractions', substudy))
        is_proximity_calculation = bool(re.search('proximity calculation', substudy))
        descriptor = ADIFeatureSpecificationUploader.ondemand_descriptor()
        is_ondemand_calculation = bool(re.search(descriptor, substudy))
        return is_fractions or is_proximity_calculation or is_ondemand_calculation

    def get_study_specifiers(self) -> tuple[str, ...]:
        self.cursor.execute('SELECT study FROM study_lookup;')
        rows = self.cursor.fetchall()
        return tuple(str(row[0]) for row in rows)

    def get_study_handle(self, study: str) -> StudyHandle:
        handles: list[StudyHandle] = []
        self.cursor.execute('SELECT DISTINCT primary_study FROM study_component;')
        rows = self.cursor.fetchall()
        for row in rows:
            handle = str(row[0])
            display_name_detail = self._get_publication_summary_text(handle)
            handles.append(StudyHandle(handle=handle, display_name_detail=display_name_detail))
        return handles[0]

    def get_collection_whitelist(self) -> tuple[str, ...]:
        try:
            self.cursor.execute('SELECT collection FROM collection_whitelist ;')
        except UndefinedTable:
            return ()
        return tuple(map(lambda row: row[0], self.cursor.fetchall()))

    def _get_publication_summary_text(self, study: str) -> str:
        query = '''
        SELECT publisher, date_of_publication
        FROM publication
        WHERE study=%s AND document_type=\'Article\'
        ;
        '''
        row = GetSingleResult.row(self.cursor, query=query, parameters=(study,),)
        if row is None:
            publication_summary_text = ''
        else:
            publisher, publication_date = row
            year_match = re.search(r'^\d{4}', publication_date)
            if year_match:
                year = year_match.group()
                publication_summary_text = f'{publisher} {year}'
            else:
                publication_summary_text = publisher
        return publication_summary_text

    def _get_contact(self, study: str) -> StudyContact:
        row = GetSingleResult.row(
            self.cursor,
            query='''
            SELECT name, contact_reference
            FROM study_contact_person
            WHERE study=%s
            ''',
            parameters=(study,),
        )
        row = cast(tuple, row)
        return StudyContact(
            name=row[0],
            email_address=row[1] if self._rough_check_is_email(row[1]) else ''
        )

    @staticmethod
    def _rough_check_is_email(string):
        return not re.match('^[A-Za-z0-9+_.-]+@([^ ]+)$', string) is None

    def _get_data_release(self, study: str) -> DataRelease:
        query = '''
        SELECT publisher, internet_reference, date_of_publication
        FROM publication
        WHERE study=%s AND document_type=\'Dataset\'
        ;
        '''
        row = GetSingleResult.row(self.cursor, query=query, parameters=(study,),)
        row = cast(tuple, row)
        return DataRelease(**dict(zip(['repository', 'url', 'date'], row)))

    def _get_publication(self, study: str) -> Publication:
        query = '''
        SELECT title, internet_reference, date_of_publication
        FROM publication
        WHERE study=%s AND document_type=\'Article\'
        ;
        '''
        row = GetSingleResult.row(self.cursor, query=query, parameters=(study,),)
        if row is None:
            row = ('', '', '')
        title, url, date = row
        first_author_name = GetSingleResult.string(
            self.cursor,
            query='''
            SELECT person FROM author
            WHERE publication=%s
            ORDER BY regexp_replace(ordinality, '[^0-9]+', '', 'g')::int
            ;
            ''',
            parameters=(title,),
            or_else_value='',
        )
        return Publication(title=title, url=url, first_author_name=first_author_name, date=date)

    def _get_assay(self, measurement_study: str) -> Assay:
        name = GetSingleResult.string(
            self.cursor,
            query='SELECT assay FROM specimen_measurement_study WHERE name=%s;',
            parameters=(measurement_study,),
        )
        return Assay(name=name)

    def get_number_cells(self, study: str, verbose: bool=False) -> int:
        components = self.get_study_components(study)
        access = CellsAccess(self.cursor)
        number_cells = 0
        samples = self._get_specimens(components.measurement)
        if verbose:
            logger.info(f'Counting cells for {study}')
        for i, sample in enumerate(samples):
            raw, _ = access.get_cells_data(sample)
            sample_number_cells = int.from_bytes(raw[0:4])
            number_cells += sample_number_cells
            if verbose:
                if i < 50:
                    logger.info(f'{sample_number_cells} ({sample})')
                if i == 50:
                    logger.info('...')
        return number_cells

    def get_number_cells_by_sample(self, study: str, verbose: bool=False) -> tuple[tuple[str, int], ...]:
        components = self.get_study_components(study)
        access = CellsAccess(self.cursor)
        samples = self._get_specimens(components.measurement)
        if verbose:
            logger.info(f'Retrieving cell counts for {study}')
        counts: list[tuple[str, int]] = []
        for i, sample in enumerate(samples):
            raw, _ = access.get_cells_data(sample)
            sample_number_cells = int.from_bytes(raw[0:4])
            counts.append((sample, sample_number_cells))
            if verbose:
                if i < 50:
                    logger.info(f'{sample_number_cells} ({sample})')
                if i == 50:
                    logger.info('...')
        return tuple(counts)

    def _get_number_cells(self) -> int:
        self.cursor.execute('SELECT * FROM all_samples_count;')
        rows = tuple(self.cursor.fetchall())
        if len(rows) == 0:
            logger.error('Cell counts not computed.')
            return 0
        return int(rows[0][0])

    def _get_number_channels(self, specimen_measurement_study: str) -> int:
        query = '''
        SELECT count(*)
        FROM biological_marking_system bms
        WHERE bms.study=%s
        ;
        '''
        return GetSingleResult.integer(
            self.cursor,
            query=query,
            parameters=(specimen_measurement_study,),
        )

    def _get_number_specimens(self, specimen_measurement_study: str) -> int:
        return GetSingleResult.integer(
            self.cursor,
            query='''
            SELECT count(DISTINCT specimen)
            FROM specimen_data_measurement_process
            WHERE study=%s
            ;
            ''',
            parameters=(specimen_measurement_study,),
        )

    def _get_specimens(self, specimen_measurement_study: str) -> tuple[str, ...]:
        query='''
            SELECT DISTINCT specimen
            FROM specimen_data_measurement_process
            WHERE study=%s
            ;
        '''
        self.cursor.execute(query, (specimen_measurement_study,))
        return tuple(map(lambda row: row[0], tuple(self.cursor.fetchall())))

    def _get_number_composite_phenotypes(self, analysis_study: str) -> int:
        return GetSingleResult.integer(
            self.cursor,
            query='''
            SELECT count(DISTINCT cell_phenotype)
            FROM cell_phenotype_criterion
            WHERE study=%s
            ;
            ''',
            parameters=(analysis_study,),
        )

    def _get_counts_summary(self, components: StudyComponents) -> CountsSummary:
        return CountsSummary(
            specimens=self._get_number_specimens(components.measurement),
            cells=self._get_number_cells(),
            channels=self._get_number_channels(components.measurement),
            composite_phenotypes=self._get_number_composite_phenotypes(components.analysis),
        )

    def _get_institution(self, study: str) -> Institution:
        name = GetSingleResult.string(
            self.cursor,
            query='SELECT institution FROM study WHERE study_specifier=%s; ',
            parameters=(study,),
        )
        return Institution(name=name)

    @simple_instance_method_cache(maxsize=10)
    def get_specimen_names(self, study: str) -> tuple[str, ...]:
        query = '''
        SELECT specimen
        FROM specimen_data_measurement_process sdmp
        JOIN study_component sc ON sc.component_study=sdmp.study
        WHERE sc.primary_study=%s
        '''
        self.cursor.execute(query, (study,))
        rows = self.cursor.fetchall()
        return tuple(sorted([row[0] for row in rows]))

    def has_umap(self) -> bool:
        query = '''
        SELECT COUNT(*)
        FROM ondemand_studies_index
        WHERE specimen=%s ;
        '''
        self.cursor.execute(query, (VIRTUAL_SAMPLE,))
        rows = self.cursor.fetchall()
        return rows[0][0] > 0

    def has_intensities(self) -> bool:
        query = '''
        SELECT COUNT(*)
        FROM ondemand_studies_index
        WHERE blob_type=%s ;
        '''
        self.cursor.execute(query, ('feature_matrix with intensities',))
        rows = self.cursor.fetchall()
        return rows[0][0] > 0

    def get_curation_notes(self) -> str | None:
        query = 'SELECT txt FROM curation_notes;'
        try:
            self.cursor.execute(query)
            rows = tuple(self.cursor.fetchall())
        except UndefinedTable:
            return None
        if len(rows) == 0:
            return None
        return ' '.join([r[0] for r in rows])
