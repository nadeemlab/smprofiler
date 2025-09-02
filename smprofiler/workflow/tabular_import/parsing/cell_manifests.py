"""Source file parsing for cell-level data."""

from io import BytesIO as StringIO
import base64
from typing import cast

import shapefile  # type: ignore
import pandas as pd
from psycopg import Connection as PsycopgConnection

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

logger = colorized_logger(__name__)


class CellManifestsParser(SourceToADIParser):
    """Source file parsing for metadata at the level of the cell manifest set."""
    scope: RangeDefinition | None

    def __init__(self, fields, **kwargs):
        super().__init__(fields, **kwargs)
        self.dataset_design = TabularCellMetadataDesign(**kwargs)
        self.scope = None

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
