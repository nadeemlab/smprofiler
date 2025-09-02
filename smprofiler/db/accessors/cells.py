"""Convenience accessor of all cell data for a given sample."""
from pickle import loads as pickle_loads
from typing import Iterable
from typing import cast
from itertools import islice
from itertools import product

import zstandard  # type: ignore

from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_SPEC1
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_SPEC2
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_COMPRESSED
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY
from smprofiler.ondemand.defaults import WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY
from smprofiler.db.exchange_data_formats.cells import CellsData
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.database_connection import SimpleReadOnlyProvider
from smprofiler.db.accessors.feature_names import fetch_one_or_else
from smprofiler.db.accessors.feature_names import get_ordered_feature_names
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

class NoContinuousIntensitiesError(ValueError):
    def __init__(self, context: str):
        message = f'No continuous intensities available for: {context}'
        super().__init__(message)
        self.message = message


class CellsAccess(SimpleReadOnlyProvider):
    """Retrieve cell-level data for a sample."""

    def get_cells_data(
        self,
        sample: str,
        *,
        cell_identifiers: tuple[int, ...] = (),
        accept_encoding: tuple[str, ...] = (),
    ) -> tuple[CellsData, str | None]:
        if "br" in accept_encoding and cell_identifiers == ():
            self.cursor.execute(
                '''
                SELECT blob_contents
                FROM ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s;
                ''',
                (sample, VIRTUAL_SAMPLE_COMPRESSED if sample == VIRTUAL_SAMPLE else 'cell_data_brotli'),
            )
            compressed = self.cursor.fetchone()
            if compressed is not None:
                return compressed[0], 'br'
            logger.error(f'Requested "br" (Brotli) compressed blob that does not exist for {sample}.')

        raw = CellsAccess._zip_location_and_phenotype_data(
            self._get_location_data(sample, cell_identifiers),
            self._get_phenotype_data(sample, cell_identifiers),
        )

        if "zstd" in accept_encoding:
            return zstandard.compress(raw), "zstd"

        return raw, None

    def get_cells_data_intensity(
        self,
        sample: str,
        accept_encoding: tuple[str, ...] = (),
    ) -> CellsData:
        if accept_encoding != ('br',):
            raise ValueError('Only "br" (brotli) encoding is supported.')
        compressed = self._retrieve_blob(sample, FEATURE_MATRIX_WITH_INTENSITIES)
        if compressed is None:
            self.cursor.execute('SELECT specimen, blob_type FROM ondemand_studies_index;')
            rows = tuple(self.cursor.fetchall())
            for row in rows[0:min(len(rows), 20)]:
                print(row)
            if len(rows) > 20:
                print('...')
            raise NoContinuousIntensitiesError(sample)
        return cast(bytes, compressed[0])

    def _retrieve_blob(self, sample: str, blob_type: str) -> tuple[bytes] | None:
        self.cursor.execute(
            '''
            SELECT blob_contents
            FROM ondemand_studies_index
            WHERE specimen=%s AND blob_type=%s;
            ''',
            (sample, blob_type),
        )
        return self.cursor.fetchone()

    def get_cells_data_intensity_whole_study_subsample(
        self,
        study: str,
        accept_encoding: tuple[str, ...] = (),
    ) -> CellsData:
        if accept_encoding != ('br',):
            raise ValueError('Only "br" (brotli) encoding is supported.')
        compressed = self._retrieve_blob('', FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY)
        if compressed is None:
            raise NoContinuousIntensitiesError(study)
        return cast(bytes, compressed[0])

    def get_cells_data_intensity_whole_study_subsample_binary_only(
        self,
        study: str,
        accept_encoding: tuple[str, ...] = (),
    ) -> CellsData:
        if accept_encoding != ('br',):
            raise ValueError('Only "br" (brotli) encoding is supported.')
        compressed = self._retrieve_blob('', WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY)
        if compressed is None:
            raise NoContinuousIntensitiesError(study)
        return cast(bytes, compressed[0])

    def get_ordered_feature_names(self) -> BitMaskFeatureNames:
        return get_ordered_feature_names(self.cursor)

    def _get_location_data(
        self,
        sample: str,
        cell_identifiers: tuple[int, ...],
    ) -> dict[int, tuple[float, float]]:
        if sample == VIRTUAL_SAMPLE:
            blob_type = VIRTUAL_SAMPLE_SPEC2[1]
        else:
            blob_type = 'centroids'
        locations: dict[int, tuple[float, float]] = pickle_loads(
            fetch_one_or_else(
                '''
                SELECT blob_contents
                FROM ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s;
                ''',
                (sample, blob_type),
                self.cursor,
                f'Requested centroids data for "{sample}" not found in database.'
            )
        )[sample]
        if cell_identifiers == ():
            return locations
        return {key: locations[key] for key in set(cell_identifiers).intersection(locations.keys())}

    def _get_phenotype_data(
        self,
        sample: str,
        cell_identifiers: tuple[int, ...],
    ) -> dict[int, bytes]:
        if sample == VIRTUAL_SAMPLE:
            blob_type = VIRTUAL_SAMPLE_SPEC1[1]
        else:
            blob_type = 'feature_matrix'
        index_and_expressions = bytearray(fetch_one_or_else(
            '''
            SELECT blob_contents
            FROM ondemand_studies_index
            WHERE specimen=%s AND blob_type=%s;
            ''',
            (sample, blob_type),
            self.cursor,
            f'Requested phenotype data for "{sample}" not found in database.',
        ))
        byte_count = len(index_and_expressions)
        if byte_count % 16 != 0:
            message = f'Expected 16 bytes per cell in binary representation of phenotype data, got {byte_count}.'  # pylint: disable=line-too-long
            logger.error(message)
            raise ValueError(message)
        bytes_iterator = index_and_expressions.__iter__()
        masks = dict(
            (int.from_bytes(batch[0:8], byteorder='little'), bytes(batch[8:16]))
            for batch in self._batched(bytes_iterator, 16)
        )
        if cell_identifiers == ():
            return masks
        return {key: masks[key] for key in set(cell_identifiers).intersection(masks.keys())}

    @staticmethod
    def _batched(iterable: Iterable, batch_size: int):
        iterator = iter(iterable)
        while batch := tuple(islice(iterator, batch_size)):
            yield batch

    @classmethod
    def _zip_location_and_phenotype_data(
        cls,
        location_data: dict[int, tuple[float, float]],
        phenotype_data: dict[int, bytes],
    ) -> CellsData:
        identifiers = sorted(list(location_data.keys()))
        _identifiers = sorted(list(phenotype_data.keys()))
        if _identifiers != identifiers:
            message = 'Mismatch of cell sets for location and phenotype data.'
            raise ValueError(message)

        if len(identifiers) == 0:
            header = b''.join(map(
                lambda i: int(i).to_bytes(4),
                (0, 0, 0, 0, 0)
            ))
            return b''.join((header, b''))

        cls._check_consecutive(identifiers)
        extrema = {
            (operation[1], index): operation[0](map(lambda p: p[index-1], location_data.values()))
            for operation, index in product(((min, 'min'), (max, 'max')), (1, 2))
        }
        min_x = extrema[('min', 1)]
        min_y = extrema[('min', 2)]
        if min_x <= 1 or min_y <= 1:
            keys = set(location_data.keys())
            for key in keys:
                location = location_data[key]
                location_data[key] = (location[0] - min_x + 1, location[1] - min_y + 1)
        combined = tuple(
            (i, location_data[i], phenotype_data[i])
            for i in identifiers
        )
        serial = b''.join(map(cls._format_cell_bytes, combined))
        if len(serial) % 20 != 0:
            message = f'Expected exactly 20 bytes per cell to be created. Got total {len(serial)}.'
            logger.error(message)
            raise ValueError(message)
        cell_count = int(len(serial) / 20)
        extrema = {
            (operation[1], index): operation[0](map(lambda p: p[index-1], location_data.values()))
            for operation, index in product(((min, 'min'), (max, 'max')), (1, 2))
        }
        header = b''.join(map(
            lambda i: int(i).to_bytes(4),
            (cell_count,extrema[('min',1)],extrema[('max',1)],extrema[('min',2)],extrema[('max',2)])
        ))
        return b''.join((header, serial))

    @classmethod
    def _check_consecutive(cls, identifiers: list[int]):
        offset = identifiers[0]
        for id1, id2 in zip(identifiers, range(len(identifiers))):
            if id1 != id2 + offset:
                message = f'Identifiers {identifiers[0]}..{identifiers[-1]} not consecutive: {id1} should be {id2 + offset}.'  # pylint: disable=line-too-long
                logger.warning(message)
                break

    @classmethod
    def _format_cell_bytes(cls, args: tuple[int, tuple[float, float], bytes]) -> bytes:
        identifier, location, phenotype = args
        return b''.join((
            identifier.to_bytes(4),
            int(location[0]).to_bytes(4),
            int(location[1]).to_bytes(4),
            phenotype,
        ))
