from json import loads as json_loads
from typing import Any

from psycopg import Cursor as PsycopgCursor

from smprofiler.db.accessors.study import StudyAccess
from smprofiler.ondemand.defaults import ORDERED_FEATURE_NAMES
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.exchange_data_formats.metrics import Channel
from smprofiler.ondemand.cache_store import CacheStore
from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def get_ordered_feature_names_abstract(study: str, cache_store: CacheStore) -> BitMaskFeatureNames:
    names = json_loads(cache_store.get_blob(study, None, ORDERED_FEATURE_NAMES).decode('utf-8'))
    return BitMaskFeatureNames(
        names=tuple(Channel(symbol=n, full_name='') for n in names)
    )

def get_ordered_feature_names(cursor: PsycopgCursor) -> BitMaskFeatureNames:
    study = StudyAccess(cursor).get_primary_study()
    cache_store = get_cache_store(None)
    return get_ordered_feature_names_abstract(study, cache_store)



