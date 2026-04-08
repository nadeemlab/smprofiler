"""Utility for writing expression matrices in a specially-compressed binary format."""
from itertools import product
from typing import cast
import json
import brotli
from numpy.typing import NDArray
from numpy import arange
from numpy import uint64 as np_uint64

from smprofiler.ondemand.defaults import ORDERED_FEATURE_NAMES
from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.standalone_utilities.float8 import encode_float8_with_clipping
from smprofiler.standalone_utilities.float8 import decode as decode_float8
from smprofiler.ondemand.cache_store import get_cache_store

logger = colorized_logger(__name__)


def compress_bitwise_to_int(feature_vector: NDArray) -> int:
    return int(feature_vector.dot(1 << arange(feature_vector.size)))

def filter_on_ids(ids: tuple[int, ...], items: tuple) -> tuple:
    """Using 0-indexing for integer IDs, filters the items."""
    return tuple(filter(lambda i: i[0] in ids, zip(range(len(items)), items)))


class CompressedMatrixHandling:
    """Write the compressed in-memory binary format matrices to file."""
    database_config_file: str

    def __init__(self, database_config_file: str | None) -> None:
        self.database_config_file = cast(str, database_config_file)
        self.cache_store = get_cache_store(database_config_file)

    def write_feature_order(self, study: str, feature_names: tuple[str, ...]) -> None:
        feature_names_str_bytes = json.dumps(list(feature_names)).encode('utf-8')
        self.cache_store.put_blob(study, None, ORDERED_FEATURE_NAMES, feature_names_str_bytes, drop_first=True)

    def _insert_blob(self, study: str | None, blob: bytearray, specimen: str, blob_type: str, drop_first: bool=False) -> None:
        self.cache_store.put_blob(study, specimen, blob_type, cast(bytes, blob), drop_first=drop_first)

    def blob_exists(self, study: str, specimen: str, blob_type: str) -> bool:
        return self.cache_store.blob_exists(study, specimen, blob_type)

    @staticmethod
    def form_intensities_compressed_blob(
        data_array: dict[int, tuple[float, ...]],
    ):
        blob = bytearray()
        for histological_structure_id in sorted(list(data_array.keys())):
            blob.extend(int(histological_structure_id).to_bytes(4))
            for value in data_array[histological_structure_id]:
                encoded = encode_float8_with_clipping(value)
                blob.extend(encoded)
        compressed_blob = brotli.compress(blob, quality=11, lgwin=24)
        return compressed_blob

    @classmethod
    def zip_location_and_phenotype_data(
        cls,
        location_data: dict[int, tuple[float, float]],
        phenotype_data: dict[int, bytes],
    ) -> bytes:
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
    def _format_cell_bytes(cls, args: tuple[int, tuple[float, float], bytes]) -> bytes:
        identifier, location, phenotype = args
        return b''.join((
            identifier.to_bytes(4),
            int(location[0]).to_bytes(4),
            int(location[1]).to_bytes(4),
            phenotype,
        ))

    @classmethod
    def form_phenotype_bytes(cls, cell_ids: list[int], discrete_matrix: NDArray) -> dict[int, bytes]:
        phenotype_bytes: dict[int, bytes] = {}
        for cell_id, row in zip(cell_ids, discrete_matrix):
            mask = cls._bitmask(row)
            phenotype_bytes[cell_id] = int(mask).to_bytes(8, byteorder='little')
        return phenotype_bytes

    @staticmethod
    def _bitmask(values: NDArray) -> int:
        mask = 0
        for index, value in enumerate(values):
            if int(value) != 0:
                mask |= 1 << index
        return mask

    @staticmethod
    def parse_rows_location_phenotype(
        blob: bytearray | bytes,
        number_features: int,
        phenotype_mask_as_is: bool=False,
    ) -> tuple[tuple[int, ...], ...]:
        """
        If phenotype_mask_as_is is selected, the 64-bit int representation of the
        phenotype bits is kept as-is and not expanded into a tuple of 0/1s.
        """
        width = 20
        if len(blob) % width != 0:
            raise ValueError('Locations/phenotype payload should have 20 bytes per row, including the header.')
        number_rows = int(len(blob) / width)
        rows = []
        for i in range(1, number_rows):
            row_i = width * i
            id_sector = blob[row_i: row_i + 4]
            id = int.from_bytes(id_sector)
            x_sector = blob[row_i + 4: row_i + 8]
            x = int.from_bytes(x_sector)
            y_sector = blob[row_i + 8: row_i + 12]
            y = int.from_bytes(y_sector)
            p_int = int.from_bytes(blob[row_i + 12: row_i + 20], byteorder='little')
            if phenotype_mask_as_is:
                phenotype_bits = [np_uint64(p_int)]
            else:
                phenotype_bits = [(p_int >> j) % 2 for j in range(number_features)]
            rows.append(tuple([id, x, y] + phenotype_bits))
        return tuple(rows)

    @staticmethod
    def parse_rows_intensity(blob: bytearray | bytes, number_features: int) -> tuple[tuple[float | int, ...], ...]:
        width = 4 + number_features
        if len(blob) % width != 0:
            raise ValueError('Intensity payload should have 16 bytes per row.')
        number_rows = int(len(blob) / width)
        rows = []
        for i in range(number_rows):
            row_i = width * i
            id_sector = blob[row_i: row_i + 4]
            id = int.from_bytes(id_sector)
            values = tuple([id] + [decode_float8(blob[row_i + 4 + j].to_bytes()) for j in range(number_features)])
            rows.append(values)
        return tuple(rows)

