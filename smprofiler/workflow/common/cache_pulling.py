"""Do cache file pulling/creation and stashing in database."""

import brotli  # type: ignore

from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.db.accessors.feature_names import RecordNotFoundInDatabaseError
from smprofiler.db.database_connection import DBCursor
from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.workflow.common.sparse_matrix_puller import SparseMatrixPuller
from smprofiler.workflow.common.structure_centroids_puller \
    import StructureCentroidsPuller
from smprofiler.workflow.common.umap_creation import UMAPCreator
from smprofiler.workflow.common.umap_creation import NoContinuousIntensityDataError
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_COMPRESSED

logger = colorized_logger(__name__)

BROTLI_BLOB_TYPE = 'cell_data_brotli'


def cache_pull(database_config_file: str | None, study: str) -> None:
    puller1 = StructureCentroidsPuller(database_config_file)
    puller1.pull_and_write_to_files(study=study)
    puller2 = SparseMatrixPuller(database_config_file)
    puller2.pull_and_write_to_files(study=study)


def compressed_payloads_cache_pull(database_config_file: str | None, study: str) -> None:
    with DBCursor(database_config_file=database_config_file, study=study) as cursor:
        access = CellsAccess(cursor)
        specimens = _get_specimens(cursor)
        for specimen in list(specimens) + [VIRTUAL_SAMPLE]:
            _compress_and_save_combo_feature_matrix(access, specimen, cursor)


def _compress_and_save_combo_feature_matrix(access: CellsAccess, specimen: str, cursor) -> None:
    try:
        raw = access._zip_location_and_phenotype_data(
            access._get_location_data(specimen, cell_identifiers=()),
            access._get_phenotype_data(specimen, cell_identifiers=()),
        )
    except RecordNotFoundInDatabaseError as error:
        message = f'Did not find location or phenotype data for "{specimen}".'
        if specimen == VIRTUAL_SAMPLE:
            logger.warning(message)
            return
        else:
            logger.error(message)
            raise error
    if specimen == VIRTUAL_SAMPLE:
        blob_type = VIRTUAL_SAMPLE_COMPRESSED
    else:
        blob_type = BROTLI_BLOB_TYPE
    compressed_data = brotli.compress(raw, quality=11, lgwin=24)
    cursor.execute('''
        INSERT INTO
        ondemand_studies_index (
            specimen,
            blob_type,
            blob_contents
        )
        VALUES (%s, %s, %s);
    ''', (specimen, blob_type, compressed_data))
    logger.info('Created brotli compressed cell data for %s', specimen)


def _get_specimens(cursor) -> tuple[str, ...]:
    cursor.execute('''
        SELECT sdmp.specimen
        FROM specimen_data_measurement_process sdmp
        ORDER BY sdmp.specimen;
    ''')
    return tuple(map(lambda row: row[0], tuple(cursor.fetchall())))


def umap_cache_pull(database_config_file: str | None, study: str):
    creator = UMAPCreator(database_config_file, study)
    try:
        creator.create()
    except NoContinuousIntensityDataError:
        logger.warning(f'No continuous intensity data was found for "{study}".')


def intensities_cache_pull(database_config_file: str | None, study: str) -> None:
    puller = SparseMatrixPuller(database_config_file)
    puller.pull_and_write_to_files(study=study, continuous=True)
