"""Convenience accessor of all cell data for a given sample."""
from typing import cast
from typing import Iterable
from itertools import islice

import brotli

from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.ondemand.cache_store import CacheStore
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
from smprofiler.db.accessors.primary_study import get_primary_study
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

class NoContinuousIntensitiesError(ValueError):
    def __init__(self, context: str):
        message = f'No continuous intensities available for: {context}'
        super().__init__(message)
        self.message = message


class CellsAccess(SimpleReadOnlyProvider):
    """Retrieve cell-level data for a sample."""

    def _get_cache_store(self) -> CacheStore:
        database_config_file = self.database_config_file
        return get_cache_store(database_config_file)

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
            cache_store = get_cache_store(self.database_config_file)
            study = get_primary_study(self.cursor)
            if not cache_store.blob_exists(study, sample, blob_type):
                logger.error(f'Requested "br" (Brotli) compressed blob that does not exist for {sample}.')
                return bytes(), None
            compressed = cache_store.get_blob(study, sample, blob_type)
            if 'br' in accept_encoding:
                return compressed, 'br'
            else:
                raw = brotli.decompress(compressed)
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
        cache_store = get_cache_store(None)
        study = get_primary_study(self.cursor)
        blob_type = FEATURE_MATRIX_WITH_INTENSITIES
        if not cache_store.blob_exists(study, sample, blob_type):
            logger.error(f'Requested "br" (Brotli) compressed intensities blob that does not exist for {sample}.')
            raise NoContinuousIntensitiesError(sample)
        compressed = cache_store.get_blob(study, sample, blob_type)
        if 'br' in accept_encoding:
            return cast(bytes, compressed)
        else:
            return brotli.decompress(compressed)

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
        cache_store = get_cache_store(None)
        study = get_primary_study(self.cursor)
        blob_type = FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY
        if not cache_store.blob_exists(study, None, blob_type):
            logger.error('Requested "br" (Brotli) compressed intensities blob that does not exist for whole study subsample.')
            raise NoContinuousIntensitiesError(study)
        compressed = cache_store.get_blob(study, None, blob_type)
        return cast(bytes, compressed)

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
        cache_store = get_cache_store(None)
        study = get_primary_study(self.cursor)
        blob_type = WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY
        if not cache_store.blob_exists(study, None, blob_type):
            logger.error('Requested "br" (Brotli) compressed intensities blob that does not exist for whole study subsample (binary only).')
            raise NoContinuousIntensitiesError(study)
        compressed = cache_store.get_blob(study, None, blob_type)
        return cast(bytes, compressed)

    def get_ordered_feature_names(self) -> BitMaskFeatureNames:
        return get_ordered_feature_names(self.cursor)

    @staticmethod
    def _batched(iterable: Iterable, batch_size: int):
        iterator = iter(iterable)
        while batch := tuple(islice(iterator, batch_size)):
            yield batch

