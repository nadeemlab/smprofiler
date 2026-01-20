"""Source file parsing for cell-level data."""

from io import BytesIO as StringIO
import base64
import pickle
from typing import cast

import shapefile  # type: ignore
import pandas as pd
from psycopg import Connection as PsycopgConnection
import brotli  # type: ignore

from smprofiler.workflow.tabular_import.tabular_dataset_design\
    import TabularCellMetadataDesign
from smprofiler.workflow.common.file_io import compute_sha256
from smprofiler.workflow.common.logging.performance_timer import PerformanceTimer
from smprofiler.workflow.common.file_identifier_schema \
    import get_input_filename_by_identifier
from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.workflow.tabular_import.parsing.range_definition import RangeDefinition
from smprofiler.workflow.tabular_import.parsing.range_definition import RangeDefinitionFactory
from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.ondemand.compressed_matrix_writer import CompressedMatrixWriter
from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.workflow.common.umap_creation import UMAPCreator
from smprofiler.workflow.common.umap_creation import NoContinuousIntensityDataError
from smprofiler.workflow.common.umap_creation import UMAP_POINT_LIMIT

logger = colorized_logger(__name__)


class CellManifestsParser(SourceToADIParser):
    """Source file parsing for metadata at the level of the cell manifest set."""
    scope: RangeDefinition | None

    def __init__(self, fields, **kwargs):
        super().__init__(fields, **kwargs)
        self.dataset_design = TabularCellMetadataDesign(**kwargs)
        self.scope = None
        self.study_name = cast(str | None, kwargs.get('study_name'))
        self.database_config_file = cast(str | None, kwargs.get('database_config_file'))
        self.build_caches_in_memory = bool(kwargs.get('build_caches_in_memory', False))

    def parse(self,
        connection: PsycopgConnection,
        file_manifest_file,
        chemical_species_identifiers_by_symbol,
    ):
        """Retrieve each cell manifest, and parse records for:
        - histological structure identification
        - histological structure
        - shape file
        - expression quantification
        """
        if self.build_caches_in_memory:
            self._parse_and_build_caches(
                file_manifest_file,
                chemical_species_identifiers_by_symbol,
            )
            return
        timer = PerformanceTimer()
        timer.record_timepoint('Initial')
        cursor = connection.cursor()
        timer.record_timepoint('Cursor opened')
        get_next = SourceToADIParser.get_next_integer_identifier
        histological_structure_identifier_index = get_next('histological_structure', cursor)
        shape_file_identifier_index = get_next('shape_file', cursor)
        expression_quantification_index = self.get_expression_quantification_last_index(cursor) + 1
        timer.record_timepoint('Retrieved next integer identifiers')
        initial_indices: dict[str, int] = {   # type: ignore
            'structure': histological_structure_identifier_index,
            'shape file': shape_file_identifier_index,
            'expression quantification': expression_quantification_index,
        }
        channel_symbols = self.get_channel_symbols(chemical_species_identifiers_by_symbol)
        final_indices: dict[str, int] = {}
        file_count = 1
        for _, cell_manifest in self.get_cell_manifests(file_manifest_file).iterrows():
            logger.debug(
                'Considering contents of file "%s".',
                cell_manifest['File ID'],
            )
            filename = get_input_filename_by_identifier(
                input_file_identifier=cell_manifest['File ID'],
                file_manifest_filename=file_manifest_file,
            )
            self.open_expression_quantification_scope(cell_manifest['Sample ID'], initial_indices['expression quantification'])
            final_indices: dict[str, int] = self.parse_cell_manifest(  # type: ignore
                cursor,
                filename,
                channel_symbols,
                initial_indices,
                timer,
                chemical_species_identifiers_by_symbol,
            )
            self.finalize_expression_quantification_scope(final_indices['expression quantification'] - 1, cursor)
            initial_indices = final_indices
            timer.record_timepoint('Completed cell manifest parsing')
            message = 'Performance report %s:\n%s'
            logger.debug(message, file_count, timer.report_string(organize_by='total time spent'))
            file_count += 1
            connection.commit()
        cursor.close()
        self.wrap_up_timer(timer)

    def open_expression_quantification_scope(self, scope_identifier: str, initial_index: int) -> None:
        logger.debug('Opening range scope with %s.', initial_index)
        self.scope = RangeDefinitionFactory.create(
            scope_identifier,
            initial_index,
            'expression_quantification',
        )

    def finalize_expression_quantification_scope(self, last_value: int, cursor):
        logger.debug('Finalizing range scope with %s.', last_value)
        RangeDefinitionFactory.finalize(cast(RangeDefinition, self.scope), last_value)
        scope = cast(RangeDefinition, self.scope)
        cursor.execute('''
        INSERT INTO range_definitions(
            scope_identifier,
            tablename,
            lowest_value,
            highest_value
        ) VALUES (%s, %s, %s, %s) ;
        ''', (scope.scope_identifier, scope.tablename, scope.lowest_value, scope.highest_value))

    def get_expression_quantification_last_index(self, cursor) -> int:
        cursor.execute('SELECT MAX(range_identifier_integer) FROM expression_quantification ;')
        last = cursor.fetchall()[0][0]
        if last is None:
            last = 0
        return last

    def insert_chunks(self,
        cursor,
        cells,
        timer,
        sha256_hash,
        channel_symbols,
        chemical_species_identifiers_by_symbol,
        histological_structure_identifier_index,
        shape_file_identifier_index,
    ):
        timer.record_timepoint('Retrieved and hashed a cell manifest')
        chunk_size = 100000
        for start in range(0, cells.shape[0], chunk_size):
            timer.record_timepoint('Starting a chunk')
            batch_cells_reference = cells.iloc[start:start + chunk_size]
            batch_cells = batch_cells_reference.reset_index(drop=True)
            records = {
                'histological_structure': [],
                'shape_file': [],
                'histological_structure_identification': [],
                'expression_quantification': [],
            }
            timer.record_timepoint('Subset cells dataframe on chunk')
            get_columns = self.dataset_design.get_exact_column_names
            feature_names, intensities_available = get_columns(channel_symbols, batch_cells.columns)
            values = {
                symbol: batch_cells[feature_names[symbol]]
                for symbol in channel_symbols
            }
            timer.record_timepoint('Retrieved feature values on chunk')

            logger.debug('Starting batch of cells that begins at index %s.', start)
            timer.record_timepoint('Started per-cell iteration')
            for j, cell in batch_cells.iterrows():
                histological_structure_identifier = str(histological_structure_identifier_index)
                histological_structure_identifier_index += 1
                shape_file_identifier = str(shape_file_identifier_index)
                shape_file_identifier_index += 1
                timer.record_timepoint('Beginning of one cell iteration')
                shape_file_contents = self.create_shape_file(cell, self.dataset_design)
                timer.record_timepoint('Created shapefile contents')
                records['histological_structure'].append((
                    histological_structure_identifier,
                    'cell',
                ))
                records['shape_file'].append((
                    shape_file_identifier,
                    'ESRI Shapefile SHP',
                    shape_file_contents,
                ))
                records['histological_structure_identification'].append((
                    histological_structure_identifier,
                    sha256_hash,
                    shape_file_identifier,
                    '\\N',
                    '',
                    '',
                    '',
                ))
                for symbol in channel_symbols:
                    target = chemical_species_identifiers_by_symbol[symbol]
                    discrete_value = values[symbol].iloc[j, 0]  # type: ignore
                    if intensities_available:
                        quantity = str(float(values[symbol].iloc[j, 1]))
                    else:
                        quantity = '\\N'
                    records['expression_quantification'].append((
                        histological_structure_identifier,
                        target,
                        quantity,
                        '',
                        '',
                        'positive' if discrete_value == 1 else 'negative',
                        '',
                    ))

            table_names = [
                'histological_structure',
                'shape_file',
                'histological_structure_identification',
                'expression_quantification',
            ]
            for tablename in table_names:
                timer.record_timepoint('Started encoding one chunk')
                values_file_contents = '\n'.join([
                    '\t'.join(r) for r in records[tablename]
                ]).encode('utf-8')
                timer.record_timepoint('Started inserting chunk into local memory')
                self.copy_from(cursor, values_file_contents, tablename)
                timer.record_timepoint('Finished inserting one chunk')
        expression_quantification_index = self.get_expression_quantification_last_index(cursor) + 1
        return {
            'structure' : histological_structure_identifier_index,
            'shape file' : shape_file_identifier_index,
            'expression quantification' : expression_quantification_index,
        }

    def copy_from(self, cursor, contents: bytes, tablename: str) -> None:
        if tablename == 'expression_quantification':
            columns = ('histological_structure', 'target', 'quantity', 'unit', 'quantification_method', 'discrete_value', 'discretization_method')
            copy_command = f"COPY {tablename} ({', '.join(columns)}) FROM STDIN"
        else:
            copy_command = f'COPY {tablename} FROM STDIN'
        with cursor.copy(copy_command) as copy:
            copy.write(contents)

    def parse_cell_manifest(self,
        cursor,
        filename,
        channel_symbols,
        initial_indices,
        timer,
        chemical_species_identifiers_by_symbol,
    ):
        histological_structure_identifier_index = initial_indices['structure']
        shape_file_identifier_index = initial_indices['shape file']
        sha256_hash = compute_sha256(filename)
        cells = pd.read_csv(filename, sep=',', na_filter=False).drop_duplicates()
        count = self.get_number_known_cells(sha256_hash, cursor)
        if count > 0 and count != cells.shape[0]:
            logger.warning(
                ('Found %s cells but %s already known from data source file "%s". '
                    ' You may need to drop bad cell records from '
                    'histological_structure_identification table, or check the source '
                    'data file\'s integrity. For now, skipping this source file.'),
                cells.shape[0],
                count,
                sha256_hash,
            )
            return {
                'structure' : histological_structure_identifier_index,
                'shape file' : shape_file_identifier_index,
            }
        if count == cells.shape[0]:
            message = 'Found exactly %s cells recorded from data source file "%s". Skipping.'
            logger.debug(message, count,  sha256_hash)
            return {
                'structure' : histological_structure_identifier_index,
                'shape file' : shape_file_identifier_index,
            }
        if count == 0:
            indices = self.insert_chunks(
                cursor,
                cells,
                timer,
                sha256_hash,
                channel_symbols,
                chemical_species_identifiers_by_symbol,
                histological_structure_identifier_index,
                shape_file_identifier_index,
            )
            logger.info('Parsed records for %s cells from "%s".', cells.shape[0], sha256_hash)
            return indices
        return None

    def get_cell_manifests(self, file_manifest_file):
        file_metadata = pd.read_csv(file_manifest_file, sep='\t')
        return file_metadata[
            file_metadata['Data type'] == self.dataset_design.get_cell_manifest_descriptor()
        ]

    def get_channel_symbols(self, chemical_species_identifiers_by_symbol):
        recognized_channel_symbols = self.dataset_design.get_channel_names()
        symbols = set(chemical_species_identifiers_by_symbol.keys())
        missing = symbols.difference(recognized_channel_symbols)
        if len(missing) > 0:
            logger.warning('Cannot find channel metadata for %s .', str(missing))
        return symbols.difference(missing)

    def get_number_known_cells(self, sha256_hash, cursor):
        query = (
            'SELECT COUNT(*) '
            'FROM histological_structure_identification '
            f'WHERE data_source = {self.get_placeholder()} ;'
        )
        cursor.execute(query, (sha256_hash,))
        count = cursor.fetchall()[0][0]
        return count

    def get_polygon_coordinates(self, cell, dataset_design):
        columns = dataset_design.get_box_limit_column_names()
        extrema = [cell[c] for c in columns]
        xmin, xmax, ymin, ymax = extrema
        return [
            [xmin, ymin],
            [xmin, ymax],
            [xmax, ymax],
            [xmax, ymin],
        ]

    def create_shape_file(self, cell, dataset_design):
        shp = StringIO()
        shx = StringIO()
        dbf = StringIO()
        points = self.get_polygon_coordinates(cell, dataset_design)
        points = points + [points[0]]
        writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
        writer.field('name', 'C')
        writer.poly([points])
        writer.record()
        writer.close()
        encoded = base64.b64encode(shp.getvalue())
        ascii_representation = encoded.decode('utf-8')
        return ascii_representation

    def wrap_up_timer(self, timer):
        df = timer.report(organize_by='fraction')
        df.to_csv('performance_report.csv', index=False)

    def _parse_and_build_caches(
        self,
        file_manifest_file,
        chemical_species_identifiers_by_symbol,
    ) -> None:
        if self.study_name is None:
            raise ValueError('study_name is required to build caches in memory.')
        measurement_study = SourceToADIParser.get_measurement_study_name(self.study_name)
        cache_store = get_cache_store(self.database_config_file)
        writer = CompressedMatrixWriter(self.database_config_file)

        channel_symbols = self.get_channel_symbols(chemical_species_identifiers_by_symbol)
        specimens_by_measurement_study: dict[str, list[str]] = {measurement_study: []}
        target_by_symbol = {
            symbol: chemical_species_identifiers_by_symbol[symbol]
            for symbol in channel_symbols
        }
        symbols_by_target = {
            target: symbol
            for symbol, target in target_by_symbol.items()
        }
        ordered_targets = sorted(list(symbols_by_target.keys()))
        ordered_symbols = [symbols_by_target[target] for target in ordered_targets]
        target_index_lookup = {target: i for i, target in enumerate(ordered_targets)}
        target_index_lookups = {measurement_study: target_index_lookup}
        target_by_symbols = {measurement_study: target_by_symbol}

        umap_discrete_rows: list[list[int]] = []
        umap_continuous_rows: list[list[float]] = []
        for _, cell_manifest in self.get_cell_manifests(file_manifest_file).iterrows():
            specimen = cell_manifest['Sample ID']
            filename = get_input_filename_by_identifier(
                input_file_identifier=cell_manifest['File ID'],
                file_manifest_filename=file_manifest_file,
            )
            cells = pd.read_csv(filename, sep=',', na_filter=False).drop_duplicates()
            umap_remaining = UMAP_POINT_LIMIT - len(umap_discrete_rows)
            umap_sample = self._build_cache_artifacts_for_cells(
                cells,
                specimen,
                ordered_symbols,
                writer,
                cache_store,
                measurement_study,
                umap_remaining=umap_remaining,
            )
            if umap_sample is not None:
                discrete_sample, continuous_sample = umap_sample
                umap_discrete_rows.extend(discrete_sample)
                umap_continuous_rows.extend(continuous_sample)
            specimens_by_measurement_study[measurement_study].append(specimen)

        writer.write_index(
            specimens_by_measurement_study,
            target_index_lookups,
            target_by_symbols,
        )

        if len(umap_continuous_rows) > 0:
            discrete_df = self._build_umap_frame(umap_discrete_rows, ordered_symbols, 'discrete_value')
            continuous_df = self._build_umap_frame(umap_continuous_rows, ordered_symbols, 'quantity')
            creator = UMAPCreator(self.database_config_file, self.study_name)
            try:
                creator.create_from_dense_frames(continuous_df, discrete_df, ordered_symbols)
            except NoContinuousIntensityDataError:
                logger.warning('No continuous intensity data was found for UMAP creation.')
        else:
            logger.warning('No continuous intensity data was found for UMAP creation.')

    def _build_cache_artifacts_for_cells(
        self,
        cells: pd.DataFrame,
        specimen: str,
        ordered_symbols: list[str],
        writer: CompressedMatrixWriter,
        cache_store,
        measurement_study: str,
        umap_remaining: int,
    ) -> tuple[list[list[int]], list[list[float]]] | None:
        feature_names, intensities_available = self.dataset_design.get_exact_column_names(
            ordered_symbols,
            cells.columns,
        )
        dichotomized_columns = [feature_names[symbol][0] for symbol in ordered_symbols]
        intensity_columns = [feature_names[symbol][1] for symbol in ordered_symbols] if intensities_available else []

        cell_ids = list(range(1, cells.shape[0] + 1))
        xmin, xmax, ymin, ymax = self.dataset_design.get_box_limit_column_names()
        centroid_x = (cells[xmin].astype(float) + cells[xmax].astype(float)) / 2.0
        centroid_y = (cells[ymin].astype(float) + cells[ymax].astype(float)) / 2.0
        centroids = {
            cell_id: (float(x), float(y))
            for cell_id, x, y in zip(cell_ids, centroid_x, centroid_y)
        }

        discrete_matrix = cells[dichotomized_columns].astype(int).to_numpy()
        data_arrays: dict[int, int] = {}
        phenotype_bytes: dict[int, bytes] = {}
        for cell_id, row in zip(cell_ids, discrete_matrix):
            compressed = self._compress_bitmask(row)
            data_arrays[cell_id] = compressed
            phenotype_bytes[cell_id] = int(compressed).to_bytes(8, 'little')

        writer.write_specimen(data_arrays, measurement_study, specimen)
        cache_store.put_blob(
            self.study_name,
            specimen,
            'centroids',
            pickle.dumps({specimen: centroids}),
            drop_first=True,
        )

        raw = CellsAccess._zip_location_and_phenotype_data(centroids, phenotype_bytes)
        compressed = brotli.compress(raw, quality=11, lgwin=24)
        cache_store.put_blob(
            self.study_name,
            specimen,
            'cell_data_brotli',
            compressed,
            drop_first=True,
        )

        umap_sample: tuple[list[list[int]], list[list[float]]] | None = None
        if intensities_available:
            intensity_matrix = cells[intensity_columns].astype(float).to_numpy()
            scale = 1.0 / 10.0
            intensity_arrays: dict[int, tuple[float, ...]] = {}
            for cell_id, row in zip(cell_ids, intensity_matrix):
                intensity_arrays[cell_id] = tuple(float(value) * scale for value in row)
            writer._write_intensities_data_array_to_db(
                intensity_arrays,
                measurement_study,
                specimen,
            )
            if umap_remaining > 0:
                sample_count = min(len(discrete_matrix), umap_remaining)
                umap_sample = (
                    discrete_matrix[:sample_count].astype(int).tolist(),
                    intensity_matrix[:sample_count].astype(float).tolist(),
                )
        return umap_sample

    @staticmethod
    def _compress_bitmask(values) -> int:
        compressed = 0
        for index, value in enumerate(values):
            if int(value) != 0:
                compressed |= 1 << index
        return compressed

    @staticmethod
    def _build_umap_frame(
        rows: list[list[float | int]],
        ordered_symbols: list[str],
        modifier: str,
    ) -> pd.DataFrame:
        columns = pd.MultiIndex.from_tuples([(modifier, symbol) for symbol in ordered_symbols])
        index = list(range(1, len(rows) + 1))
        return pd.DataFrame(rows, columns=columns, index=index)
