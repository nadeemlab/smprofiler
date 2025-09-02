from math import floor
import random

import brotli  # type: ignore
from numpy import uint64 as np_int64
from pydantic import BaseModel

from smprofiler.ondemand.computers.counts_computer import CountsComputer
from smprofiler.standalone_utilities.float8 import decode as decode8
from smprofiler.standalone_utilities.float8 import encode as encode8
from smprofiler.db.accessors.feature_names import get_ordered_feature_names
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.accessors.study import StudyAccess
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.db.accessors.cells import NoContinuousIntensitiesError
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.ondemand.compressed_matrix_writer import CompressedMatrixWriter
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY
from smprofiler.ondemand.defaults import WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY
from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger(__name__)

class SubsampleCountAndThresholds(BaseModel):
    specimen: str
    count: int
    thresholds: tuple[int, ...]

class SubsampleMetadata(BaseModel):
    subsample_counts: tuple[SubsampleCountAndThresholds, ...]
    channel_order: tuple[str, ...]

DEFAULT_MAX = 1000000

class Subsampler:
    study: str
    database_config_file: str | None
    maximum_number_cells: int
    verbose: bool

    def __init__(self, study: str, database_config_file: str | None, maximum_number_cells: int = DEFAULT_MAX, verbose: bool=False):
        self.study = study
        self.database_config_file = database_config_file
        self.maximum_number_cells = maximum_number_cells
        self.verbose = verbose
        if not self._continuous_intensity_example_available():
            return
        self._compute_and_store()

    @classmethod
    def cache_exists(cls, study: str, database_config_file: str | None) -> bool:
        blob_type = FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY
        return CompressedMatrixWriter(database_config_file).blob_exists(study, '', blob_type)

    def _continuous_intensity_example_available(self) -> bool:
        with DBCursor(study=self.study, database_config_file=self.database_config_file) as cursor:
            cursor.execute('SELECT specimen FROM ondemand_studies_index WHERE LENGTH(specimen)>0 AND specimen!=%s LIMIT 1;', (VIRTUAL_SAMPLE,))
            samples = tuple(cursor.fetchall())
            if len(samples) == 0:
                return False
            sample = samples[0][0]
            access = CellsAccess(cursor)
            try:
                _ = access.get_cells_data_intensity(sample, accept_encoding=('br',))
            except NoContinuousIntensitiesError as error:
                logger.error(error.message)
                return False
        return True

    def _compute_and_store(self) -> None:
        blob = bytearray()

        metadata, original_sample_sizes = self._form_subsample_metadata()
        blob.extend(metadata.model_dump_json().encode('utf-8'))

        file_separator = int.to_bytes(28)
        blob.extend(file_separator)
        offset = len(blob)

        for subsample_count, original in zip(
            metadata.subsample_counts,
            original_sample_sizes,
        ):
            sample_name, subsample_size = subsample_count.specimen, subsample_count.count
            blob.extend(self._get_subsample(sample_name, subsample_size, original, len(metadata.channel_order)))

        if self.verbose:
            logger.info('Compressing blob.')
        compressed_blob = brotli.compress(blob, quality=11, lgwin=24)

        if self.verbose:
            logger.info('Writing blob to database.')
        blob_type = FEATURE_MATRIX_WITH_INTENSITIES_SUBSAMPLE_WHOLE_STUDY
        CompressedMatrixWriter(self.database_config_file)._insert_blob(
            self.study, compressed_blob, '', blob_type, drop_first=True,
        )

        if self.verbose:
            logger.info('Compressing binary portion separately, and writing to database.')
        blob_type = WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY
        compressed_blob = brotli.compress(blob[offset:], quality=11, lgwin=24)
        CompressedMatrixWriter(self.database_config_file)._insert_blob(
            self.study, compressed_blob, '', blob_type, drop_first=True,
        )

    def _form_subsample_metadata(self) -> tuple[SubsampleMetadata, tuple[int, ...]]:
        with DBCursor(study=self.study, database_config_file=self.database_config_file) as cursor:
            s = StudyAccess(cursor).get_number_cells_by_sample(self.study, verbose=self.verbose)
        sample_names_alphabetical, sample_sizes = tuple(zip(*sorted(list(s), key=lambda pair: pair[0])))
        subsample_sizes_same_order = self._adjust_sample_sizes(sample_sizes)
        channel_order = self._get_channel_names()
        thresholds = self._determine_thresholds(sample_names_alphabetical, channel_order)
        subsample_counts = tuple(map(
            lambda args: SubsampleCountAndThresholds(
                specimen=args[0],
                count=args[1],
                thresholds=args[2],
            ),
            zip(sample_names_alphabetical, subsample_sizes_same_order, thresholds),
        ))
        return SubsampleMetadata(subsample_counts=subsample_counts, channel_order=channel_order), sample_sizes

    def _determine_thresholds(
        self,
        samples: tuple[str, ...],
        channel_names: tuple[str, ...],
    ) -> list[tuple[int, ...]]:
        t: list[tuple[int, ...]] = []
        with DBCursor(study=self.study, database_config_file=self.database_config_file) as cursor:
            access = CellsAccess(cursor)
            for sample in samples:
                logger.info(f'Determing thresholds for {sample}.')
                compressed = access.get_cells_data_intensity(sample, accept_encoding=('br',))
                intensities = brotli.decompress(compressed)
                compressed, _ = access.get_cells_data(sample, accept_encoding=('br',))
                phenotypes = brotli.decompress(compressed)
                t.append(self._determine_thresholds_one_sample(intensities, phenotypes, channel_names))
        return t

    def _determine_thresholds_one_sample(self, intensities: bytes, phenotypes: bytes, channel_names: tuple[str, ...]) -> tuple[int, ...]:
        sample_number_cells = int.from_bytes(phenotypes[0:4])
        header_offset = 20
        row_width = 20
        N = len(channel_names)
        low_values: dict[str, list[float]] = {n: [] for n in channel_names}
        high_values: dict[str, list[float]] = {n: [] for n in channel_names}
        signatures = {n: CountsComputer._compute_signature((n,), channel_names) for n in channel_names}
        for i in range(sample_number_cells):
            position1 = header_offset + i*row_width + 12
            mask_size = 8
            phenotype_mask_i = np_int64(int.from_bytes(
                phenotypes[position1: position1 + mask_size], byteorder='little'
            ))
            position2 = (N + 4)*i
            intensities_i = intensities[position2: position2 + N]
            for j, n in enumerate(channel_names):
                value = decode8(int.to_bytes(intensities_i[j]))
                if phenotype_mask_i & signatures[n] == signatures[n]:
                    high_values[n].append(value)
                else:
                    low_values[n].append(value)
        def ensure_nontrivial(v: int) -> int:
            if v == 0:
                return 1
            return v
        return tuple(
            ensure_nontrivial(int.from_bytes(encode8(
                self._aggregate_low_high_values(
                    low_values[n],
                    high_values[n],
                )
            )))
            for n in channel_names
        )

    def _aggregate_low_high_values(self, low: list[float], high: list[float]) -> float:
        """
        Reconstructs a threshold value dividing low and high values, using the max of the lows
        and the min of the highs.
        """
        if len(high) == 0 and len(low) == 0:
            message = 'No values recorded when iterating over cells for a given phenotype.'
            logger.error(message)
            raise ValueError(message)
        if len(high) == 0:
            return max(low)
        if len(low) == 0:
            return min(high)
        return (max(low) + min(high)) / 2

    def _adjust_sample_sizes(self, sample_sizes: tuple[int, ...]) -> tuple[int, ...]:
        total = sum(list(sample_sizes))
        if total <= self.maximum_number_cells:
            return sample_sizes
        deflator = float(self.maximum_number_cells / total)
        approximates = list(map(lambda s: floor(s*deflator), sample_sizes))
        index = 0
        while sum(approximates) < self.maximum_number_cells:
            value = approximates[index]
            original = sample_sizes[index]
            if value < original:
                approximates[index] = value + 1
            index = (index + 1) % len(approximates)
        if not sum(approximates) == self.maximum_number_cells:
            logger.error('Something was wrong with subsampling logic, too many cells selected.')
        return tuple(approximates)

    def _get_channel_names(self) -> tuple[str, ...]:
        with DBCursor(study=self.study, database_config_file=self.database_config_file) as cursor:
            n = get_ordered_feature_names(cursor)
        return tuple(map(lambda channel: channel.symbol, n.names))

    def _get_subsample(self, sample: str, size: int, original: int, number_channels: int) -> bytes:
        if self.verbose:
            logger.info(f'Subsampling: {sample} ({size}/{original} cells)')
        with DBCursor(study=self.study, database_config_file=self.database_config_file) as cursor:
            access = CellsAccess(cursor)
            compressed = access.get_cells_data_intensity(sample, accept_encoding=('br',))
        raw = brotli.decompress(compressed)
        random.seed(10001)
        indices = random.sample(list(range(original)), size)
        blob = bytearray()
        N = number_channels
        for i in indices:
            position = (N + 4)*i
            blob.extend(raw[position: position + N])
        return blob
