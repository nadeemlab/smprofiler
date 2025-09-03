"""Utility for writing expression matrices in a specially-compressed binary format."""

from typing import cast
import json
import brotli  # type: ignore

from smprofiler.db.ondemand_studies_index import get_counts
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import retrieve_primary_study
from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.standalone_utilities.float8 import encode_float8_with_clipping
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES

logger = colorized_logger(__name__)


class CompressedMatrixWriter:
    """Write the compressed in-memory binary format matrices to file."""
    database_config_file: str

    def __init__(self, database_config_file: str | None) -> None:
        self.database_config_file = cast(str, database_config_file)

    def write_specimen(
        self,
        data: dict[int, int] | dict[int, tuple[float, ...]],
        study_name: str,
        specimen: str,
        continuous: bool=False,
    ) -> None:
        if continuous:
            self._write_intensities_data_array_to_db(cast(dict[int, tuple[float, ...]], data), study_name, specimen)
        else:
            self._write_data_array_to_db(cast(dict[int, int], data), study_name, specimen)

    def write_index(self,
        specimens_by_measurement_study: dict[str, list[str]],
        target_index_lookups: dict,
        target_by_symbols: dict,
    ) -> None:
        study_names = sorted(list(specimens_by_measurement_study.keys()))
        for measurement_study_name in sorted(study_names):
            index_item: dict[str, str | list] = {}
            index_item['specimen measurement study name'] = measurement_study_name
            index_item['target index lookup'] = target_index_lookups[measurement_study_name]
            index_item['target by symbol'] = target_by_symbols[measurement_study_name]
            index_str = json.dumps({'': [index_item]})
            index_str_as_bytes = index_str.encode('utf-8')
            study = retrieve_primary_study(self.database_config_file, measurement_study_name)
            with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
                insert_query = '''
                    INSERT INTO
                    ondemand_studies_index (
                        specimen,
                        blob_type,
                        blob_contents
                    )
                    VALUES (%s, %s, %s) ;
                '''
                cursor.execute(insert_query, (None, 'expressions_index', index_str_as_bytes))
                cursor.close()
            logger.debug(f'Wrote expression index to database {study} .')

    def _insert_blob(self, study: str | None, blob: bytearray, specimen: str, blob_type: str, drop_first: bool=False) -> None:
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
            if drop_first:
                drop = '''
                DELETE FROM
                ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s ;
                '''
                cursor.execute(drop, (specimen, blob_type))
            insert_query = '''
                INSERT INTO
                ondemand_studies_index (
                    specimen,
                    blob_type,
                    blob_contents)
                VALUES (%s, %s, %s) ;
            '''
            cursor.execute(insert_query, (specimen, blob_type, blob))
            cursor.close()

    def blob_exists(self, study: str, specimen: str, blob_type: str) -> bool:
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
            query = '''
            SELECT COUNT(*) FROM
            ondemand_studies_index
            WHERE specimen=%s AND blob_type=%s ;
            '''
            cursor.execute(query, (specimen, blob_type))
            count = tuple(cursor.fetchall())
        if count[0][0] > 1:
            logger.error(f'ondemand_studies_index is corrupt, multipe values for specimen/blobtype {(specimen, blob_type)}')
            return True
        if count[0][0] == 1:
            return True
        return False

    def _write_intensities_data_array_to_db(
        self,
        data_array: dict[int, tuple[float, ...]],
        measurement_study_name: str,
        specimen: str,
        study_name: str | None = None,
    ):
        blob = bytearray()
        for histological_structure_id in sorted(list(data_array.keys())):
            blob.extend(int(histological_structure_id).to_bytes(4))
            for value in data_array[histological_structure_id]:
                encoded = encode_float8_with_clipping(value)
                blob.extend(encoded)
        if study_name is None:
            study_name = retrieve_primary_study(self.database_config_file, measurement_study_name)
        compressed_blob = brotli.compress(blob, quality=11, lgwin=24)
        self._insert_blob(study_name, compressed_blob, specimen, FEATURE_MATRIX_WITH_INTENSITIES)

    def _write_data_array_to_db(
        self,
        data_array: dict[int, int],
        measurement_study_name: str,
        specimen: str,
    ) -> None:
        blob = bytearray()
        for histological_structure_id, entry in data_array.items():
            blob.extend(histological_structure_id.to_bytes(8, 'little'))
            blob.extend(entry.to_bytes(8, 'little'))
        study_name = retrieve_primary_study(self.database_config_file, measurement_study_name)
        self._insert_blob(study_name, blob, specimen, 'feature_matrix')

    def expressions_indices_already_exist(self, study: str | None = None):
        counts = get_counts(self.database_config_file, 'expressions_index', study=study)
        for _study, count in counts.items():
            if count > 1:
                message = f'Too many ({count}) expression index files for study {_study}.'
                raise ValueError(message)
        return all(count == 1 for count in counts.values())
