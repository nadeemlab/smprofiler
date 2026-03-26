from json import loads as json_loads
from typing import Any

from psycopg import Cursor as PsycopgCursor

from smprofiler.ondemand.defaults import ORDERED_FEATURE_NAMES
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.exchange_data_formats.metrics import Channel
from smprofiler.ondemand.cache_store import CacheStore
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def get_ordered_feature_names_abstract(cache_store: CacheStore) -> BitMaskFeatureNames:
    cache_store.get

def get_ordered_feature_names(cursor: PsycopgCursor) -> BitMaskFeatureNames:

    names = json_loads(bytearray(fetch_one_or_else(
        f'''
            SELECT blob_contents
            FROM ondemand_studies_index osi
            WHERE blob_type='{ORDERED_FEATURE_NAMES}';
        ''',
        (),
        cursor,
        'No feature metadata for the given study.',
    )).decode('utf-8'))
    return BitMaskFeatureNames(
        names=tuple(Channel(symbol=n, full_name='') for n in names)
    )


class RecordNotFoundInDatabaseError(ValueError):
    pass


def fetch_one_or_else(
    query: str,
    args: tuple,
    cursor: PsycopgCursor,
    error_message: str,
) -> Any:
    cursor.execute(query, args)
    fetched = cursor.fetchone()
    if fetched is None:
        logger.error(error_message)
        raise RecordNotFoundInDatabaseError(error_message)
    return fetched[0]

