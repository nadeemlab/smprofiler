from os import environ as os_environ
from abc import ABC
from abc import abstractmethod
from typing import Literal

from numpy import asarray
from numpy import uint64 as np_int64

from psycopg.errors import UniqueViolation

from smprofiler.db.database_connection import DBCursor
from smprofiler.ondemand.computers.cell_data_arrays import CellDataArrays
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.ondemand.add_feature_value import add_feature_value
from smprofiler.ondemand.job_reference import ComputationJobReference
from smprofiler.apiserver.request_scheduling.counts_scheduler import CountsScheduler
from smprofiler.apiserver.request_scheduling.computation_scheduler import GenericComputationScheduler
from smprofiler.workflow.common.export_features import \
    ADIFeatureSpecificationUploader
from smprofiler.ondemand.providers.study_component_extraction import ComponentGetter
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.database_connection import DBConnection
from smprofiler.ondemand.cell_data_cache import CellDataCache
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class GenericJobComputer(ABC):
    job: ComputationJobReference
    connection: DBConnection

    def __init__(self, job: ComputationJobReference, cache: CellDataCache, connection: DBConnection):
        self.job = job
        self.cache = cache
        self.connection = connection

    @abstractmethod
    def compute(self) -> None:
        raise NotImplementedError

    def get_cell_data_arrays(self) -> CellDataArrays:
        study = self.job.study
        sample = self.job.sample
        cell_identifiers = self._get_cells_selected()
        if len(cell_identifiers) == 0 and self.cache.has(study, sample):
            raw, feature_names = self.cache.retrieve(study, sample)
        else:
            with DBCursor(connection=self.connection, study=study) as cursor:
                access = CellsAccess(cursor)
                raw, _ = access.get_cells_data(sample, cell_identifiers=cell_identifiers)
                feature_names = access.get_ordered_feature_names()
            if len(cell_identifiers) == 0:
                self.cache.consider_insertion(study, sample, (raw, feature_names))
        number_cells = int.from_bytes(raw[0:4])
        if number_cells == 0:
            return CellDataArrays(None, None, feature_names, None)  # type: ignore
        location = asarray((self._get_parts(4, 8, raw), self._get_parts(8, 12, raw)))
        self._expect_number(location.shape[1], number_cells)
        phenotype = asarray(self._get_parts(12, 20, raw, byteorder='little'))
        self._expect_number(phenotype.shape[0], number_cells)
        identifiers = asarray(self._get_parts(0, 4, raw))
        self._expect_number(identifiers.shape[0], number_cells)
        return CellDataArrays(location, phenotype, feature_names, identifiers)

    def _get_cells_selected(self) -> tuple[int, ...]:
        with DBCursor(connection=self.connection, study=self.job.study) as cursor:
            query = 'SELECT histological_structure FROM cell_set_cache WHERE feature=%s ;'
            cursor.execute(query, (str(self.job.feature_specification),))
            return tuple(map(lambda row: int(row[0]), cursor.fetchall()))

    @staticmethod
    def _get_parts(
        start: int, end: int, raw: bytes, byteorder: Literal['big', 'little']='big',
    ) -> tuple[np_int64, ...]:
        offset = 20
        period = 20
        return tuple(map(
            lambda batch: np_int64(int.from_bytes(batch[start:end], byteorder=byteorder)),
            CellsAccess._batched(raw[offset:], period),
        ))

    @staticmethod
    def _expect_number(got: int, expected: int) -> None:
        if got != expected:
            raise ValueError(f'Unexpected number of cells, got {got}, expected {expected}.')

    def handle_insert_value(self, value: float | None, allow_null: bool=True) -> None:
        if value is not None:
            self._insert_value(value)
            self._pop_off_queue()
        else:
            self._warn_no_value()
            if allow_null:
                self._insert_null()
                self._pop_off_queue()

    def _warn_no_value(self) -> None:
        specification = str(self.job.feature_specification)
        study = self.job.study
        sample = self.job.sample
        logger.warning(f'Feature {specification} ({sample}, {study}) could not be computed, worker generated None. May insert None.')

    def _insert_value(self, value: float | int) -> None:
        study = self.job.study
        specification = str(self.job.feature_specification)
        sample = self.job.sample
        with DBCursor(connection=self.connection, study=study) as cursor:
            try:
                add_feature_value(specification, sample, str(value), cursor)
            except UniqueViolation:
                logger.warning(f'({specification}, {sample}) value already exists, can\'t insert {value}')

    def _pop_off_queue(self) -> None:
        with DBCursor(connection=self.connection, study=self.job.study) as cursor:
            query = 'DELETE FROM quantitative_feature_value_queue WHERE feature=%s and subject=%s;'
            cursor.execute(query, (int(self.job.feature_specification), self.job.sample))

    def _insert_null(self) -> None:
        study = self.job.study
        specification = str(self.job.feature_specification)
        sample = self.job.sample
        with DBCursor(connection=self.connection, study=study) as cursor:
            try:
                add_feature_value(specification, sample, None, cursor)
            except UniqueViolation:
                logger.warning(f'({specification}, {sample}) value already exists, can\'t insert {None}')

    def handle_excessive_sample_size(self, cell_number_limit_variable: str , cell_number_limit_default: int) -> bool:
        if cell_number_limit_variable in os_environ:
            cell_number_limit = int(os_environ[cell_number_limit_variable])
        else:
            cell_number_limit = cell_number_limit_default
            logger.warning(f'You should set {cell_number_limit_variable} in the environment. Using default: {cell_number_limit_default}.')
        cell_number = self._get_cell_number()
        if cell_number is None:
            logger.warning('Cell counts feature not yet computed. Not imposing a cell number limit.')
            return False
        if cell_number > cell_number_limit:
            logger.warning(f'({self.job.feature_specification}, {self.job.sample}) cell number {cell_number} exceeds limit {cell_number_limit}, not attempting computation.')
            self._insert_null()
            self._pop_off_queue()
            return True
        return False

    def _get_cell_counts_feature(self) -> str | None:
        with DBCursor(connection=self.connection, study=self.job.study) as cursor:
            measurement_study_name = ComponentGetter.get_study_components(cursor, self.job.study).measurement
            data_analysis_study = ADIFeatureSpecificationUploader.get_data_analysis_study(measurement_study_name, cursor)
            criteria = PhenotypeCriteria(positive_markers=(), negative_markers=())
        return CountsScheduler._get_feature_specification(self.connection, self.job.study, data_analysis_study, criteria, ())

    def _get_cell_number(self) -> int | None:
        feature = self._get_cell_counts_feature()
        if feature is None:
            return None
        count = GenericComputationScheduler._query_for_computed_feature_values(self.connection, self.job.study, feature).values[self.job.sample]
        return int(count) if count is not None else None

    @staticmethod
    def retrieve_specifiers(connection: DBConnection, study: str, feature_specification: str) -> tuple[str, list[str]]:
        """Get specifiers for this feature specification."""
        with DBCursor(connection=connection, study=study) as cursor:
            cursor.execute('''
                SELECT fs.specifier, fs.ordinality
                FROM feature_specifier fs
                WHERE fs.feature_specification=%s ;
                ''',
                (feature_specification,),
            )
            rows = cursor.fetchall()
            specifiers = [row[0] for row in sorted(rows, key=lambda row: int(row[1]))]
            cursor.execute('''
                SELECT sc2.component_study FROM feature_specification fs
                JOIN study_component sc ON sc.component_study=fs.study
                JOIN study_component sc2 ON sc.primary_study=sc2.primary_study
                WHERE fs.identifier=%s AND
                    sc2.component_study IN ( SELECT name FROM specimen_measurement_study )
                    ;
                ''',
                (feature_specification,),
            )
            study = tuple(cursor.fetchall())[0][0]
        return study, specifiers
