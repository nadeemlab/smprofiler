"""Source file parsing for cell-level data."""
from re import LOCALE
from typing import cast

from pandas import read_csv
from pandas import DataFrame 
from pandas import MultiIndex
from psycopg import Connection as PsycopgConnection
from psycopg import Cursor as PsycopgCursor
import brotli

from smprofiler.ondemand.compressed_matrix_handling import CompressedMatrixHandling
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES
from smprofiler.ondemand.defaults import LOCATION_PHENOTYPE_BROTLI
from smprofiler.workflow.tabular_import.tabular_dataset_design import TabularCellMetadataDesign
from smprofiler.workflow.common.logging.performance_timer import PerformanceTimerReporter
from smprofiler.workflow.common.file_identifier_schema import get_input_filename_by_identifier
from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.ondemand.cache_store import CacheStore
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.workflow.common.umap_creation import UMAPCreator
from smprofiler.workflow.common.umap_creation import NoContinuousIntensityDataError
from smprofiler.workflow.common.umap_creation import UMAP_POINT_LIMIT

logger = colorized_logger(__name__)

class Timing:
    """Yet another wrapper around the performance timer. To clean up the calling syntax."""

    timer: PerformanceTimerReporter

    def start(self) -> None:
        self.timer = PerformanceTimerReporter('performance_report.tsv', logger, verbose=True)

    def timepoint(self, name: str) -> None:
        self.timer.record_timepoint(name)

    def wrap_up(self) -> None:
        self.timer.wrap_up_timer()


def insert_count(count: int, cursor: PsycopgCursor) -> None:
    table = 'all_samples_count'
    cursor.execute(f'CREATE TABLE IF NOT EXISTS {table} (count INTEGER);')
    cursor.execute(f'DELETE FROM {table} ;')
    cursor.execute(f'INSERT INTO {table} VALUES ({count});')


class CellManifestsParser(SourceToADIParser):
    """Source file parsing for cell data."""

    dataset_design: TabularCellMetadataDesign
    study_name: str
    database_config_file: str | None
    cache_store: CacheStore
    timer: Timing
    connection: PsycopgConnection
    subsampled_discrete_rows: list[list[int]]
    subsampled_continuous_rows: list[list[float]]

    def __init__(self, fields, **kwargs):
        super().__init__(fields, **kwargs)
        self.dataset_design = TabularCellMetadataDesign(**kwargs)
        self.study_name = cast(str, kwargs.get('study_name'))
        self.database_config_file = cast(str | None, kwargs.get('database_config_file'))
        self.cache_store = get_cache_store(self.database_config_file)
        self.timer = Timing()

    def parse(self,
        connection: PsycopgConnection,
        file_manifest_file: str,
        chemical_species_identifiers_by_symbol: dict[str, str],
    ):
        """
        Parse each sample's cell data file, creating specialized/custom binary
        feature matrices, with discrete and continuous channels, etc.

        The dict providing target/chemical_species IDs by string name is provided
        due to the (now marginal) use case where some chemical_species records already
        existed in the database from some other study or measurement study, in which
        case the channels needed during *this* parsing phase cannot be determined
        by consulting the database only. This is necessary if multiple datasets will
        be housed in the same database, although our current usage splits each
        dataset into its own PostgresQL schema.
        """
        self.connection = connection
        self._parse_and_build_preprocessed_samples(
            file_manifest_file,
            chemical_species_identifiers_by_symbol,
        )
        logger.error('Only build_preprocessed_samples_in_memory is supported.')

    def _parse_and_build_preprocessed_samples(
        self,
        file_manifest_file: str,
        chemical_species_identifiers_by_symbol: dict[str, str],
    ) -> None:
        """
        Uses direct processing of each sample, only writing final products to the
        database that are actually used by the application.

        In the future the per-sample portion should be distributed over a multiprocessing
        pool. This is not the default due to variable per-sample memory requirements, but
        the balance of requested cores vs. available memory could be managed by the caller.
        """
        if self.study_name is None:
            raise ValueError('study_name is required to build preprocessed_samples in memory.')
        ordered_symbols, target_index_lookup, target_by_symbol = self._prepare_channel_metadata(
            chemical_species_identifiers_by_symbol,
        )
        self._loop_over_samples(file_manifest_file, ordered_symbols)
        self._write_channel_metadata(ordered_symbols)
        self._handle_umap_generation(ordered_symbols)

    def _prepare_channel_metadata(self, chemical_species_identifiers_by_symbol: dict[str, str]):
        """
        This gathers the channel metadata specific to our database schema, for:
        1. The expressions index file, annotating all of our binary per-sample payloads.
        2. The specific channel order, as needed during creation of these payloads
           after parsing source files.

        There are 3 aspects to each channel, sorted out here:
        - `index`. The 0-based integer index of the *normalized sorted* channel in the
          context of this study.
        - `chemical_species` or `target`. The database index of a chemical species
          (e.g. a specific protein).
        - `symbol`. The string name of the channel/protein/target.
        """
        channel_symbols = self._get_channel_symbols(chemical_species_identifiers_by_symbol)
        target_by_symbol = {
            symbol: chemical_species_identifiers_by_symbol[symbol]
            for symbol in channel_symbols
        }
        symbols_by_target = {
            target: symbol
            for symbol, target in target_by_symbol.items()
        }
        ordered_targets = sorted(list(symbols_by_target.keys()))
        ordered_symbols = tuple([symbols_by_target[target] for target in ordered_targets])
        target_index_lookup = {target: i for i, target in enumerate(ordered_targets)}
        return ordered_symbols, target_index_lookup, target_by_symbol

    def _loop_over_samples(
        self,
        file_manifest_file: str,
        ordered_symbols: tuple[str, ...],
    ):
        """
        Skeleton of loop over the samples.
        The real parsing is done in `_build_preprocessed_sample`.
        Subsamples are taken (for the purpose of later aggregation, for the UMAP).

        The subsampling is now an instance-level attribute to save on passing, but
        note that this breaks a potential future multiprocessing pool approach.
        """
        self.subsampled_discrete_rows: list[list[int]] = []
        self.subsampled_continuous_rows: list[list[float]] = []
        running_cell_count = 0
        for _, cell_manifest in self._get_cell_manifests(file_manifest_file).iterrows():
            self.timer.start()
            self.timer.timepoint('Starting one cell manifest')
            specimen = str(cell_manifest['Sample ID'])
            filename = get_input_filename_by_identifier(
                input_file_identifier=str(cell_manifest['File ID']),
                file_manifest_filename=file_manifest_file,
            )
            if filename is None:
                raise ValueError
            cells = read_csv(filename, sep=',', na_filter=False).drop_duplicates()
            self.timer.timepoint('Loaded one sample cells file.')
            subsampled_remaining = UMAP_POINT_LIMIT - len(self.subsampled_discrete_rows)
            subsampled, cell_count = self._build_preprocessed_sample(
                cells,
                specimen,
                ordered_symbols,
                subsampled_remaining=subsampled_remaining,
            )
            if subsampled is not None:
                discrete_sample, continuous_sample = subsampled
                self.subsampled_discrete_rows.extend(discrete_sample)
                self.subsampled_continuous_rows.extend(continuous_sample)
            running_cell_count += cell_count
            self.timer.timepoint(('Finished one cell manifest.'))
            self.timer.wrap_up()
        cursor = self.connection.cursor()
        insert_count(running_cell_count, cursor)
        self.connection.commit()
        cursor.close()

    def _build_preprocessed_sample(
        self,
        cells: DataFrame,
        specimen: str,
        ordered_symbols: tuple[str, ...],
        subsampled_remaining: int,
    ) -> tuple[tuple[list[list[int]], list[list[float]]] | None, int]:
        feature_names, intensities_available = self.dataset_design.get_exact_column_names(
            ordered_symbols,
            cells.columns,
        )
        dichotomized_columns = [feature_names[symbol][0] for symbol in ordered_symbols]
        intensity_columns = [feature_names[symbol][1] for symbol in ordered_symbols] if intensities_available else []

        cell_ids = list(range(cells.shape[0]))
        xmin, xmax, ymin, ymax = self.dataset_design.get_box_limit_column_names()
        centroid_x = (cells[xmin].astype(float) + cells[xmax].astype(float)) / 2.0
        centroid_y = (cells[ymin].astype(float) + cells[ymax].astype(float)) / 2.0
        centroids = {
            cell_id: (float(x), float(y))
            for cell_id, x, y in zip(cell_ids, centroid_x, centroid_y)
        }

        discrete_matrix = cells[dichotomized_columns].astype(int).to_numpy()
        phenotype_bytes = CompressedMatrixHandling.form_phenotype_bytes(cell_ids, discrete_matrix)

        self.timer.timepoint('Aggregating location and phenotype data.')
        raw = CompressedMatrixHandling.zip_location_and_phenotype_data(centroids, phenotype_bytes)
        compressed = brotli.compress(raw, quality=11, lgwin=24)
        self.timer.timepoint('Done aggregating location and phenotype data.')
        self.cache_store.put_blob(
            self.study_name,
            specimen,
            LOCATION_PHENOTYPE_BROTLI,
            compressed,
            drop_first=True,
        )
        self.timer.timepoint('Done putting compressed/aggregated location and phenotype data in cache.')

        subsample: tuple[list[list[int]], list[list[float]]] | None = None
        if intensities_available:
            intensity_matrix = cells[intensity_columns].astype(float).to_numpy()
            scale = 1.0 / 10.0
            intensity_arrays: dict[int, tuple[float, ...]] = {}
            for cell_id, row in zip(cell_ids, intensity_matrix):
                intensity_arrays[cell_id] = tuple(float(value) * scale for value in row)
            compressed_blob = CompressedMatrixHandling.form_intensities_compressed_blob(intensity_arrays)
            self.cache_store.put_blob(self.study_name, specimen, FEATURE_MATRIX_WITH_INTENSITIES, compressed_blob)
            logger.info('Forming and saving intensities sample (FEATURE_MATRIX_WITH_INTENSITIES).')
            if subsampled_remaining > 0:
                sample_count = min(len(discrete_matrix), subsampled_remaining)
                subsample = (
                    discrete_matrix[:sample_count].astype(int).tolist(),
                    intensity_matrix[:sample_count].astype(float).tolist(),
                )
        self.timer.timepoint('Done skimming subsample.')
        return (subsample, cells.shape[0])

    def _write_channel_metadata(
        self,
        ordered_symbols: tuple[str, ...],
    ) -> None:
        """
        Saves the feature order once and for all for the dataset, and saves it to the database.
        """
        writer = CompressedMatrixHandling(self.database_config_file)
        writer.write_feature_order(self.study_name, ordered_symbols)
        logger.info('Done writing feature order to database.')

    def _handle_umap_generation(self, ordered_symbols: tuple[str, ...]) -> None:
        if len(self.subsampled_continuous_rows) > 0:
            discrete_df = self._build_umap_frame(self.subsampled_discrete_rows, ordered_symbols, 'discrete_value')
            logger.info('Done preparing dataframe for discrete UMAP.')
            continuous_df = self._build_umap_frame(self.subsampled_continuous_rows, ordered_symbols, 'quantity')
            logger.info('Done preparing dataframe for continuous UMAP.')
            creator = UMAPCreator(self.database_config_file, self.study_name)
            try:
                creator.create_from_dense_frames(continuous_df, discrete_df, ordered_symbols)
                logger.info('Done creating UMAPs.')
            except NoContinuousIntensityDataError:
                logger.warning('No continuous intensity data was found for UMAP creation.')
        else:
            logger.warning('No continuous intensity data was found for UMAP creation.')

    def _build_umap_frame(
        self,
        rows: list[list[int]] | list[list[float]],
        ordered_symbols: tuple[str, ...],
        modifier: str,
    ) -> DataFrame:
        columns = MultiIndex.from_tuples([(modifier, symbol) for symbol in ordered_symbols])
        index = list(range(len(rows)))
        df = DataFrame(rows, columns=columns, index=index)
        scale = 1.0 / 10.0
        for c in columns:
            df[c] = scale * df[c]
        return df

    def _get_cell_manifests(self, file_manifest_file):
        file_metadata = read_csv(file_manifest_file, sep='\t')
        return file_metadata[
            file_metadata['Data type'] == self.dataset_design.get_cell_manifest_descriptor()
        ]

    def _get_channel_symbols(self, chemical_species_identifiers_by_symbol: dict[str, str]) -> set[str]:
        recognized_channel_symbols = self.dataset_design.get_channel_names()
        symbols = set(chemical_species_identifiers_by_symbol.keys())
        missing = symbols.difference(recognized_channel_symbols)
        if len(missing) > 0:
            logger.warning('Cannot find channel metadata for %s .', str(missing))
        return symbols.difference(missing)


