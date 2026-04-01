
from psycopg import Cursor as PsycopgCursor

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def get_primary_study(cursor: PsycopgCursor) -> str:
    cursor.execute('SELECT DISTINCT primary_study FROM study_component;')
    studies = tuple(map(lambda row: row[0], tuple(cursor.fetchall())))
    if len(studies) > 1:
        logger.warning(f'Multiple primary studies found in schema: {studies}')
    if len(studies) == 0:
        logger.error('No primary studies found.')
        raise ValueError
    return studies[0]


