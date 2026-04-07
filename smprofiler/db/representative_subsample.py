from math import floor
import random
from typing import cast

import brotli
from pydantic import BaseModel
from pandas import DataFrame

from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.standalone_utilities.float8 import encode as encode8
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.accessors.study import StudyAccess
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_COMPRESSED
from smprofiler.ondemand.compressed_matrix_handling import CompressedMatrixHandling
from smprofiler.db.feature_matrix_retrieval import FeatureMatrixRetrieval
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES
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
        return CompressedMatrixHandling(database_config_file).blob_exists(study, '', blob_type)

    def _continuous_intensity_example_available(self) -> bool:
        cache_store = get_cache_store(self.database_config_file)
        return cache_store.blob_exists(self.study, VIRTUAL_SAMPLE, VIRTUAL_SAMPLE_COMPRESSED)

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
        CompressedMatrixHandling(self.database_config_file)._insert_blob(
            self.study, compressed_blob, '', blob_type, drop_first=True,
        )

        if self.verbose:
            logger.info('Compressing binary portion separately, and writing to database.')
        blob_type = WHOLE_STUDY_SUBSAMPLE_BINARY_ONLY
        compressed_blob = brotli.compress(blob[offset:], quality=11, lgwin=24)
        CompressedMatrixHandling(self.database_config_file)._insert_blob(
            self.study, compressed_blob, '', blob_type, drop_first=True,
        )

    def _form_subsample_metadata(self) -> tuple[SubsampleMetadata, tuple[int, ...]]:
        with DBCursor(study=self.study, database_config_file=self.database_config_file) as cursor:
            s = StudyAccess(cursor).get_number_cells_by_sample(self.study, verbose=self.verbose)
        sample_names_alphabetical, sample_sizes = tuple(zip(*sorted(list(s), key=lambda pair: pair[0])))
        subsample_sizes_same_order = self._adjust_sample_sizes(sample_sizes)
        thresholds = self._determine_thresholds(sample_names_alphabetical)
        subsample_counts = tuple(map(
            lambda args: SubsampleCountAndThresholds(
                specimen=args[0],
                count=args[1],
                thresholds=args[2],
            ),
            zip(sample_names_alphabetical, subsample_sizes_same_order, thresholds),
        ))
        channel_order = FeatureMatrixRetrieval(self.database_config_file).feature_names(self.study)
        return SubsampleMetadata(subsample_counts=subsample_counts, channel_order=channel_order), sample_sizes

    def _determine_thresholds(
        self,
        samples: tuple[str, ...],
    ) -> list[tuple[int, ...]]:
        t: list[tuple[int, ...]] = []
        for sample in samples:
            logger.info(f'Determing thresholds for {sample}.')
            bundle = FeatureMatrixRetrieval(self.database_config_file).extract(sample, self.study, continuous_also=True)[sample]
            df = bundle.dataframe
            df_i = cast(DataFrame, bundle.continuous_dataframe)
            t.append(self._determine_thresholds_one_sample(df_i, df))
        return t

    def _determine_thresholds_one_sample(self, df_i: DataFrame, df: DataFrame) -> tuple[int, ...]:
        channel_names = [c for c in df_i.columns if not c == 'id']
        low_values: dict[str, list[float]] = {n: [] for n in channel_names}
        high_values: dict[str, list[float]] = {n: [] for n in channel_names}
        for (_, row), (_, row_i) in zip(df.iterrows(), df_i.iterrows()):
            for c in channel_names:
                value = float(cast(float, row_i[c]))
                phenotype_membership = row[c]
                if phenotype_membership == 1:
                    high_values[c].append(value)
                else:
                    low_values[c].append(value)

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
        t = None
        if len(high) == 0:
            t = max(low)
        if len(low) == 0:
            t = min(high)
        if t is None:
            t = (max(low) + min(high)) / 2
        return t

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

    def _get_subsample(self, sample: str, size: int, original: int, number_channels: int) -> bytes:
        if self.verbose:
            logger.info(f'Subsampling: {sample} ({size}/{original} cells)')
        cache_store = get_cache_store(self.database_config_file)
        raw = brotli.decompress(cache_store.get_blob(self.study, sample, FEATURE_MATRIX_WITH_INTENSITIES))
        random.seed(10001)
        indices = random.sample(list(range(original)), size)
        blob = bytearray()
        N = number_channels
        for i in indices:
            position = (N + 4)*i
            blob.extend(raw[position: position + N + 4])
        return cast(bytes, blob)


