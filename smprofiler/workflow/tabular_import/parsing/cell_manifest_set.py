"""Source file parsing for metadata at the level of a set of cell manifests."""
from os.path import getsize
import re
from typing import cast

from pandas import Series
from pandas import read_csv
from psycopg import cursor as PsycopgCursor

from \
    smprofiler.workflow.tabular_import.tabular_dataset_design \
    import TabularCellMetadataDesign
from smprofiler.workflow.common.file_io import compute_sha256
from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def cell_manifest_data_type():
    return TabularCellMetadataDesign.get_cell_manifest_descriptor()


def _create_specimen_data_measurement_process_record(
    identifier,
    specimen,
    study,
):
    return (identifier, specimen, '', '', study)


class CellManifestSetParser(SourceToADIParser):
    """Parse source files containing metadata at level of cell manifest set."""

    def parse(self, connection, file_manifest_file, study_name):
        """Retrieve the set of cell manifests (i.e. just the "metadata" for each source
        file), and parse records for:
        - specimen measurement study
        - specimen data measurement process
        - data file
        """
        file_metadata = read_csv(file_manifest_file, sep='\t')
        cell_manifests = file_metadata[
            file_metadata['Data type'] == cell_manifest_data_type()
        ]

        measurement_study = SourceToADIParser.get_measurement_study_name(study_name)
        cursor = connection.cursor()
        cursor.execute(
            self.generate_basic_insert_query('specimen_measurement_study'),
            (measurement_study, '', '', '', '', ''),
        )

        for _, cell_manifest in cell_manifests.iterrows():
            self._handle_cell_manifest(cell_manifest, measurement_study, cursor)
        logger.info('Parsed records for %s cell manifests.', cell_manifests.shape[0])
        connection.commit()
        cursor.close()

    def _handle_cell_manifest(self,
        cell_manifest: Series,
        measurement_study: str,
        cursor: PsycopgCursor,
    ):
        message = 'Considering "%s" file "%s" .'
        logger.debug(message, cell_manifest_data_type(), cell_manifest['File ID'])
        sample_id = cell_manifest['Sample ID']
        filename = cell_manifest['File name']
        sha256_hash = compute_sha256(filename)

        measurement_process_identifier = sha256_hash + ' measurement'
        cursor.execute(
            self.generate_basic_insert_query('specimen_data_measurement_process'),
            _create_specimen_data_measurement_process_record(
                measurement_process_identifier,
                sample_id,
                measurement_study,
            ),
        )
        match = re.search(r'\.([a-zA-Z0-9]{1,8})$', cell_manifest['File name'])
        if match:
            extension_string = cast(str, match.groups(1)[0])
            file_format = extension_string.upper()
        else:
            file_format = ''
        cursor.execute(
            self.generate_basic_insert_query('data_file'),
            (
                sha256_hash,
                cell_manifest['File name'],
                file_format,
                cell_manifest_data_type(),
                getsize(filename),
                measurement_process_identifier,
            ),
        )
