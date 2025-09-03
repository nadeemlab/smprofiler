"""Retrieve the "feature matrix" for a given study and store it in a binary compressed format."""

from typing import cast, Any

from pandas import DataFrame  # type: ignore
from numpy import ndarray
from numpy import arange  # type: ignore

from smprofiler.db.database_connection import retrieve_study_from_specimen
from smprofiler.db.database_connection import retrieve_study_names
from smprofiler.db.database_connection import DBCursor
from smprofiler.workflow.common.study_data_arrays import StudyDataArrays
from smprofiler.ondemand.compressed_matrix_writer import CompressedMatrixWriter
from smprofiler.workflow.common.logging.fractional_progress_reporter \
    import FractionalProgressReporter
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class CompressedDataArrays:
    """An object for in-memory storage of all expression data for each study.
    
    Where possible, channel information is stored in a compressed binary format. This necessarily
    assumes that there are 64 or fewer channels for a given study.
    """
    _studies: dict[str, StudyDataArrays]
    _store_inmemory: bool
    _specimens_by_measurement_study: dict
    _target_index_lookups: dict
    _target_by_symbols: dict

    def __init__(self, database_config_file: str | None):
        self._studies = {}
        self._store_inmemory = True
        self._specimens_by_measurement_study = {}
        self._target_index_lookups = {}
        self._target_by_symbols = {}
        self.database_config_file = database_config_file

    def set_store_inmemory(self, flag: bool) -> None:
        self._store_inmemory = flag

    def storing_locally(self) -> bool:
        return self._store_inmemory

    def get_studies(self) -> dict[str, StudyDataArrays]:
        """Returns data dictionaries, indexed by study.
        
        Returns
        -------
        A dictionary, indexed by study name. For each study, the value is a dictionary with keys:
            "target by symbol": dict[str, str]
                A dictionary, providing for each channel symbol (e.g. "CD3") the string which is
                the (typically decimal integer) identifier of the target "chemical species"
                labelled by the given symbol in the context of the given study.
            "target index lookup": dict[str, int]
                A dictionary, providing for each target "chemical species" in the above, the
                integer index (from 0 to 63) of the bit in the binary format corresponding to the
                given channel.
            "data arrays by specimen": dict[str, dict[int, int]]
                A dictionary, providing for each specimen name (for specimens collected as part of
                this study) a dictionary mapping the histological structure ID of each cell to a
                64-bit integer representing the cell's channels when converted to binary.
            "continuous data arrays by specimen": dict[str, dict[int, list[float]]]
                (Optional) A dictionary, providing for each specimen name a dictionary mapping the
                histological structure ID of each cell to a list of floats representing the value
                of each the cell's channels.
        """
        return self._studies

    def add_study_data(
        self,
        measurement_study: str,
        data_arrays_by_specimen: dict[str, dict[int, int]],
        target_index_lookup: dict[str, int],
        target_by_symbol: dict[str, str],
        continuous_data_arrays_by_specimen: dict[str, dict[int, list[float]]] | None = None,
    ) -> None:
        """Add a study's data to the in-memory data structure."""
        self._check_target_index_lookup(measurement_study, target_index_lookup)
        self._check_target_by_symbol(measurement_study, target_by_symbol)
        if not measurement_study in self._studies:
            self._studies[measurement_study] = {
                'data arrays by specimen': data_arrays_by_specimen,
                'target index lookup': target_index_lookup,
                'target by symbol': target_by_symbol,
            }
            if continuous_data_arrays_by_specimen is not None:
                key = 'continuous data arrays by specimen'
                self._studies[measurement_study][key] = continuous_data_arrays_by_specimen
        else:
            self._add_more_data_arrays(
                measurement_study,
                data_arrays_by_specimen,
                continuous_data_arrays_by_specimen=continuous_data_arrays_by_specimen,
            )

    def wrap_up_specimen(self, continuous_also: bool=False) -> None:
        if self.storing_locally():
            return
        if len(self._studies) != 1:
            message = 'Need to write exactly 1 specimen at a time, but more or fewer than 1 study are present in buffer: %s'
            raise ValueError(message % list(self._studies.keys()))
        study_name, data = list(self._studies.items())[0]
        specimens = sorted(list(data['data arrays by specimen'].keys()))
        if len(specimens) != 1:
            message = 'Need to write exactly 1 specimen at a time, but more or fewer than 1 are present: %s'
            raise ValueError(message % specimens)
        specimen = specimens[0]
        if continuous_also:
            data_specimen = cast(dict[int, tuple[float, ...]], data['continuous data arrays by specimen'][specimen])
            writer = CompressedMatrixWriter(self.database_config_file)
            writer.write_specimen(data_specimen, study_name, specimen, continuous=True)
        else:
            data_specimen = cast(dict[int, int], data['data arrays by specimen'][specimen])
            writer = CompressedMatrixWriter(self.database_config_file)
            writer.write_specimen(data_specimen, study_name, specimen)
        if study_name not in self._specimens_by_measurement_study:
            self._specimens_by_measurement_study[study_name] = []
        self._specimens_by_measurement_study[study_name].append(specimen)
        message = 'Deleting specimen data "%s" from internal memory, since it is saved to file.'
        logger.debug(message, specimen)
        del self._studies[study_name]
        assert len(self._studies) == 0

    def _sort_specimens(self) -> None:
        for study_name in self._specimens_by_measurement_study:  # pylint: disable=consider-using-dict-items
            specimens = self._specimens_by_measurement_study[study_name]
            self._specimens_by_measurement_study[study_name] = sorted(specimens)

    def wrap_up_writing(self) -> None:
        self._sort_specimens()
        if self.storing_locally():
            return
        writer = CompressedMatrixWriter(self.database_config_file)
        writer.write_index(
            self._specimens_by_measurement_study,
            self._target_index_lookups,
            self._target_by_symbols,
        )

    def _add_more_data_arrays(
        self,
        study_name: str,
        data_arrays_by_specimen: dict[str, dict[int, int]],
        continuous_data_arrays_by_specimen: dict[str, dict[int, list[float]]] | None = None,
    ):
        for key, integers_by_hsi in data_arrays_by_specimen.items():
            self._studies[study_name]['data arrays by specimen'][key] = integers_by_hsi
        if continuous_data_arrays_by_specimen is not None:
            for key, vectors_list in continuous_data_arrays_by_specimen.items():
                self._studies[study_name]['continuous data arrays by specimen'][key] = vectors_list

    def _check_target_index_lookup(
        self,
        measurement_study: str,
        target_index_lookup: dict[str, int],
    ) -> None:
        if measurement_study in self._studies:
            check = CompressedDataArrays._check_dicts_equal
            check(self._studies[measurement_study]['target index lookup'], target_index_lookup)
        else:
            self._target_index_lookups[measurement_study] = target_index_lookup

    def _check_target_by_symbol(
        self,
        measurement_study: str,
        target_by_symbol: dict[str, str],
    ) -> None:
        if measurement_study in self._studies:
            check = CompressedDataArrays._check_dicts_equal
            check(self._studies[measurement_study]['target by symbol'], target_by_symbol)
        else:
            self._target_by_symbols[measurement_study] = target_by_symbol

    @staticmethod
    def _check_dicts_equal(
        dict1: dict[str, dict[str, dict[str, Any]]],
        dict2: dict[str, Any],
    ) -> None:
        if sorted(list(dict1.keys())) != sorted(list(dict2.keys())):
            raise ValueError(f'Dictionary key sets not equal: {dict1.keys()}, {dict2.keys()}')
        for key, value in dict1.items():
            if value != dict2[key]:
                raise ValueError(f'Dictionary values not equal: {value}, {dict2[key]}')


class SparseMatrixPuller:
    """"Get sparse matrix representation of cell x channel data in database."""

    database_config_file: str | None
    _data_arrays: CompressedDataArrays

    def __init__(self, database_config_file: str | None):
        self.database_config_file = database_config_file
        self._data_arrays = CompressedDataArrays(database_config_file)

    def pull_and_write_to_files(self, study: str | None = None, continuous: bool=False) -> None:
        self._data_arrays.set_store_inmemory(False)
        if study is None:
            study_names = tuple(retrieve_study_names(self.database_config_file))
        else:
            study_names = (study,)
        logger.info('Will pull feature matrices for studies:')
        for name in study_names:
            logger.info('    %s', name)
        for study_name in study_names:
            measurement_study = self._get_measurement_study_name(study_name)
            specimens = self._get_pertinent_specimens(study_name, measurement_study)
            progress_reporter = FractionalProgressReporter(
                len(specimens),
                parts=8,
                task_and_done_message=(f'pulling sparse entries (intensities={continuous}) for study "{study_name}"', None),
                logger=logger,
            )
            for specimen in specimens:
                self.pull(specimen=specimen, continuous_also=continuous)
                self.get_data_arrays().wrap_up_specimen(continuous_also=continuous)
                progress_reporter.increment(iteration_details=specimen)
            progress_reporter.done()
        if not continuous:
            self.get_data_arrays().wrap_up_writing()

    def pull(self,
        specimen: str | None = None,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
    ) -> None:
        """Pull sparse matrices into self.data_arrays.

        Parameters
        ----------
        specimen: str | None = None
        study: str | None = None
            Which specimen to extract features for or study to extract features for all specimens
            for. Exactly one of specimen or study must be provided.
        histological_structures: set[int] | None = None
            Which histological structures to extract features for from the given study or specimen,
            by their histological structure ID. Structures not found in either the provided
            specimen or study are ignored.
            If None, all structures are fetched.
        """
        if (specimen is not None) and (study is not None):
            raise ValueError('Must specify exactly one of specimen or study, or neither.')
        self._retrieve_data_arrays(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
            continuous_also=continuous_also,
        )

    def get_data_arrays(self):
        return self._data_arrays

    def _retrieve_data_arrays(self,
        specimen: str | None = None,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
    ):
        if specimen is not None:
            study = retrieve_study_from_specimen(self.database_config_file, specimen)
        study_name_pairs = self._get_study_name_pairs(study=study)
        for study_name, measurement_study in study_name_pairs:
            self._fill_data_arrays_for_study(
                self._data_arrays,
                study_name,
                measurement_study,
                specimen=specimen,
                histological_structures=histological_structures,
                continuous_also=continuous_also,
            )

    def _fill_data_arrays_for_study(self,
        data_arrays: CompressedDataArrays,
        study_name: str,
        measurement_study: str,
        specimen: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
    ) -> None:
        specimens = self._get_pertinent_specimens(study_name, measurement_study, specimen=specimen)
        target_by_symbol = self._get_target_by_symbol(study_name, measurement_study)
        if specimen is not None:
            logger.debug('Pulling sparse entries for specimen "%s".', specimen)
        parse = self._parse_data_arrays_by_specimen
        for _specimen in specimens:
            sparse_entries = self._get_sparse_entries(
                study_name,
                specimen=_specimen,
                histological_structures=histological_structures,
            )
            if len(sparse_entries) == 0:
                continue
            parsed = parse(sparse_entries, _specimen, continuous_also=continuous_also)
            data_arrays_by_specimen, \
                target_index_lookup, \
                continuous_data_arrays_by_specimen = parsed
            data_arrays.add_study_data(
                measurement_study,
                data_arrays_by_specimen,
                target_index_lookup,
                target_by_symbol,
                continuous_data_arrays_by_specimen=continuous_data_arrays_by_specimen,
            )

    @classmethod
    def get_pertinent_specimens(
        cls,
        database_config_file: str,
        study: str,
        measurement_study: str,
        specimen: str | None,
    ) -> tuple[str, ...]:
        return SparseMatrixPuller(database_config_file)._get_pertinent_specimens(
            study,
            measurement_study,
            specimen,
        )

    def _get_pertinent_specimens(self,
        study_name: str,
        measurement_study: str,
        specimen: str | None = None,
    ) -> tuple[str, ...]:
        with DBCursor(database_config_file=self.database_config_file, study=study_name) as cursor:
            if specimen is not None:
                cursor.execute('''
                SELECT sdmp.specimen
                FROM specimen_data_measurement_process sdmp
                WHERE sdmp.study=%s
                    AND sdmp.specimen=%s
                ;
                ''', (measurement_study, specimen))
                if len(cursor.fetchall()) == 0:
                    raise ValueError(f'Specimen "{specimen}" not found in study "{measurement_study}".')
                return (specimen,)
            cursor.execute('''
            SELECT sdmp.specimen
            FROM specimen_data_measurement_process sdmp
            WHERE sdmp.study=%s
            ORDER BY sdmp.specimen
            ;
            ''', (measurement_study,))
            rows = cursor.fetchall()
        strings = [cast(str, row[0]) for row in rows]
        strings = sorted(strings)
        return tuple(strings)

    def _get_study_name_pairs(self, study: str | None = None) -> list[tuple[str, str]]:
        if study is None:
            studies = retrieve_study_names(self.database_config_file)
        else:
            studies = [study]
        pairs = [
            (_study, self._get_measurement_study_name(_study))
            for _study in studies
        ]
        return sorted(pairs, key=lambda x: x[1])

    def _get_measurement_study_name(self, study: str) -> str:
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
            cursor.execute('''
            SELECT sms.name FROM specimen_measurement_study sms
            JOIN study_component sc ON sc.component_study=sms.name
            WHERE sc.primary_study=%s
            ;
            ''', (study,))
            rows = cursor.fetchall()
        return cast(str, rows[0][0])

    def _get_sparse_entries(self,
        study_name: str,
        specimen: str,
        histological_structures: set[int] | None = None,
    ) -> list[tuple[str, str, int, str, str]]:
        sparse_entries: list = []
        number_log_messages = 0
        with DBCursor(database_config_file=self.database_config_file, study=study_name) as cursor:
            query = self._get_sparse_matrix_query_specimen_specific(
                cursor,
                specimen,
                histological_structures,
            )
            cursor.execute(query)
            total = cursor.rowcount
            while cursor.rownumber < total - 1:
                current_number_stored = len(sparse_entries)
                sparse_entries.extend(cursor.fetchmany(size=self._get_batch_size()))
                received = len(sparse_entries) - current_number_stored
                logger.debug('Received %s entries from DB.', received)
                number_log_messages = number_log_messages + 1
            if number_log_messages > 1:
                logger.debug('Received %s sparse entries total from DB.', len(sparse_entries))
        return sparse_entries

    def _get_sparse_matrix_query_specimen_specific(self,
        cursor,
        specimen: str,
        histological_structures: set[int] | None,
    ) -> str:
        structures_present = histological_structures is not None
        parameters: list[str | tuple[str, ...] | int] = []
        range_definition = SparseMatrixPuller._retrieve_expressions_range(cursor, specimen)
        query = self._sparse_entries_query(structures_present)
        if histological_structures is not None:
            query = query % (range_definition[0], range_definition[1], f'{tuple(str(hs_id) for hs_id in histological_structures)}')
        else:
            query = query % (range_definition[0], range_definition[1])
        return query

    @staticmethod
    def _retrieve_expressions_range(cursor, scope: str) -> tuple[int, int]:
        query = '''
        SELECT lowest_value, highest_value
        FROM range_definitions
        WHERE scope_identifier=%s AND tablename='expression_quantification' ;
        '''
        cursor.execute(query, (scope,))
        return cursor.fetchall()[0]

    @staticmethod
    def _sparse_entries_query(histological_structures_condition: bool = False) -> str:
        return f'''
        SELECT
            eq.histological_structure,
            eq.target,
            CASE WHEN discrete_value='positive' THEN 1 ELSE 0 END AS coded_value,
            eq.quantity as quantity
        FROM expression_quantification eq
        WHERE eq.range_identifier_integer BETWEEN %s AND %s
            {'AND eq.histological_structure IN %s' if histological_structures_condition else ''}
        ORDER BY eq.histological_structure, eq.target
        ;
        '''

    def _get_batch_size(self) -> int:
        return pow(10, 6)

    def _parse_data_arrays_by_specimen(self,
        sparse_entries: list[tuple[str, str, int, str, str]],
        specimen: str,
        continuous_also: bool = False,
    ) -> tuple[
        dict[str, dict[int, int]],
        dict[str, int],
        dict[str, dict[int, list[float]]] | None,
    ]:
        """
        If continuous_also is True, the last entry in the return value will contain
        intensities data for each structure (cell). These are currently scaled down
        by a factor of 10, in case the intensity values as stored in the database
        tables exceed 1.0 (the limit for downstream encoding). Ideally (for the
        future) these should be downscaled in advance so that this fudge factor
        would not needed.
        """
        target_index_lookup = self._get_target_index_lookup(sparse_entries)
        data_arrays_by_specimen: dict[str, dict[int, int]] = {}
        continuous_data_arrays_by_specimen: dict[str, dict[int, list[float]]] | None = {} \
            if continuous_also else None

        df = DataFrame(
            sparse_entries,
            columns=['histological_structure', 'target', 'coded_value', 'quantity'],
        )
        grouped = df.groupby('histological_structure')
        if specimen not in data_arrays_by_specimen:
            data_arrays_by_specimen[specimen] = {}
        for histological_structure, df_group in grouped:
            df_group.sort_values(by=['target'], inplace=True)
            hs_id = int(histological_structure)

            binary = df_group['coded_value'].astype(int).to_numpy()
            self._check_targets(list(df_group['target']), target_index_lookup)
            compressed = SparseMatrixPuller._compress_bitwise_to_int(binary)
            data_arrays_by_specimen[specimen][hs_id] = compressed

            if continuous_data_arrays_by_specimen is not None:
                if specimen not in continuous_data_arrays_by_specimen:
                    continuous_data_arrays_by_specimen[specimen] = {}
                scale = 1.0 / 10.0
                continuous_data_arrays_by_specimen[specimen][hs_id] = \
                    list(map(lambda v: v*scale, df_group['quantity'].astype(float).to_list()))
        return data_arrays_by_specimen, target_index_lookup, continuous_data_arrays_by_specimen

    def _check_targets(self, targets: list[str], target_index_lookup: dict) -> None:
        if len(targets) > len(target_index_lookup):
            raise ValueError(f'Got {len(targets)} expression values for some cell, expected {len(target_index_lookup)} or fewer.')
        for target, i in target_index_lookup.items():
            if targets[i] != target:
                raise ValueError(f'Some cell had wrong target "{targets[i]}" at position {i}, expected {target}.')

    @classmethod
    def _compress_bitwise_to_int(cls, feature_vector: ndarray) -> int:
        return int(feature_vector.dot(1 << arange(feature_vector.size)))

    def _get_target_index_lookup(self,
        sparse_entries: list[tuple[str, str, int, str, str]],
    ) -> dict[str, int]:
        target_set = set(entry[1] for entry in sparse_entries)
        targets = sorted(list(target_set))
        lookup = {
            target: i
            for i, target in enumerate(targets)
        }
        return lookup

    def _get_target_by_symbol(self, study_name: str, measurement_study: str) -> dict[str, str]:
        query = '''
        SELECT cs.identifier, cs.symbol
        FROM chemical_species cs
        JOIN biological_marking_system bms ON bms.target=cs.identifier
        WHERE bms.study=%s
        ;
        '''
        with DBCursor(database_config_file=self.database_config_file, study=study_name) as cursor:
            cursor.execute(query, (measurement_study,))
            rows = cursor.fetchall()
        if len(rows) != len(set(row[1] for row in rows)):
            message = 'The symbols are not unique identifiers of the targets. The symbols are: %s'
            logger.error(message, [row[1] for row in rows])
        target_by_symbol = {row[1]: row[0] for row in rows}
        return target_by_symbol
