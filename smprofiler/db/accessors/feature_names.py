from json import loads as json_loads
from typing import Any

from psycopg import Cursor as PsycopgCursor

from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.exchange_data_formats.metrics import Channel
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def get_ordered_feature_names(cursor) -> BitMaskFeatureNames:
    expressions_index = json_loads(bytearray(fetch_one_or_else(
        '''
        SELECT blob_contents
        FROM ondemand_studies_index osi
        WHERE blob_type='expressions_index';
        ''',
        (),
        cursor,
        'No feature metadata for the given study.',
    )).decode('utf-8'))[''][0]
    lookup1: dict[str, int] = expressions_index['target index lookup']
    lookup2: dict[str, str] = expressions_index['target by symbol']
    target_from_index = {value: key for key, value in lookup1.items()}
    symbol_from_target = {value: key for key, value in lookup2.items()}
    indices = sorted(list(target_from_index.keys()))
    names = tuple(map(
        lambda i: symbol_from_target[target_from_index[i]],
        indices,
    ))
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
