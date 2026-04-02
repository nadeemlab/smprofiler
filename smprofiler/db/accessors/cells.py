"""Convenience accessor of all cell data for a given sample."""
from typing import cast
from typing import Iterable
from itertools import product
from itertools import islice

import brotli

from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_COMPRESSED
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES
from smprofiler.ondemand.defaults import LOCATION_PHENOTYPE_BROTLI
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY
from smprofiler.ondemand.defaults import WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY
from smprofiler.db.exchange_data_formats.cells import CellsData
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.database_connection import SimpleReadOnlyProvider
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
        """
        The location and discrete phenotype data for each cell in a given sample.
        The format is the custom optimized binary format.

        Individual cell identifiers are temporarily not supported and for cases
        involving such identifiers a different method should be used.
        """
        if cell_identifiers == ():
            blob_type = VIRTUAL_SAMPLE_COMPRESSED if sample == VIRTUAL_SAMPLE else LOCATION_PHENOTYPE_BROTLI 
            compressed = self._retrieve_blob(sample, blob_type)
            if compressed is None:
                logger.error(f'Requested "br" (Brotli) compressed blob that does not exist for {sample}.')
                return bytes(), None
            if 'br' in accept_encoding:
                return compressed[0], 'br'
            else:
                raw = brotli.decompress(compressed[0])
                return raw, None
        raise ValueError('Unhandled case for requested cells data.')

    def get_cells_data_intensity(
        self,
        sample: str,
        accept_encoding: tuple[str, ...] = (),
    ) -> CellsData:
        """
        The channel intensity values for each cell in a given sample.
        The format is the custom optimized binary format, the variant with custom
        8-bit floats.
        """
        compressed = self._retrieve_blob(sample, FEATURE_MATRIX_WITH_INTENSITIES)
        if compressed is None:
            self.cursor.execute('SELECT specimen, blob_type FROM ondemand_studies_index;')
            rows = tuple(self.cursor.fetchall())
            for row in rows[0:min(len(rows), 20)]:
                print(row)
            if len(rows) > 20:
                print('...')
            raise NoContinuousIntensitiesError(sample)
        if 'br' in accept_encoding:
            return cast(bytes, compressed[0])
        else:
            return brotli.decompress(compressed[0])

    def _retrieve_blob(self, sample: str, blob_type: str) -> tuple[bytes] | None:
        """
        General purpose retrieval of the binary objects stored in the database.
        These are feature matrices of various types. See `ondemand.defaults.py`
        for some of the valid blob types.
        """
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
        """
        Like get_cells_data but for the specific case of the whole-study
        subsample.
        """
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
        """
        Like get_cells_data_intensity but for the specific case of the whole-
        study subsample.
        """
        if accept_encoding != ('br',):
            raise ValueError('Only "br" (brotli) encoding is supported.')
        compressed = self._retrieve_blob('', WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY)
        if compressed is None:
            raise NoContinuousIntensitiesError(study)
        return cast(bytes, compressed[0])

    def get_ordered_feature_names(self) -> BitMaskFeatureNames:
        return get_ordered_feature_names(self.cursor)

    @classmethod  # TODO: Move to parsing related in compressed matrix handling
    def _zip_location_and_phenotype_data(
        cls,
        location_data: dict[int, tuple[float, float]],
        phenotype_data: dict[int, bytes],
    ) -> CellsData:
        """
        Combines location and phenotype data row by row. Also includes a header.

        Possibly should move to parsing.
        """
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

    @staticmethod
    def _batched(iterable: Iterable, batch_size: int):
        iterator = iter(iterable)
        while batch := tuple(islice(iterator, batch_size)):
            yield batch

