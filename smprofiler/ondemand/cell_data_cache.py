
from os import environ as os_environ
from time import time
from math import log10
from queue import PriorityQueue

from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

NegativeDataSize = int
RequestTimestamp = int
CellDataPriority = tuple[NegativeDataSize, RequestTimestamp]

class CellDataCache:
    """
    A data structure to enable one running instance of the ondemand service to
    reduce database queries for cell data payloads that it has already downloaded.

    When inserting items, `priority` values that are lowest (in the sense of operators
    of comparison `>` and `<`) correspond to items that are evicted first.

    _determine_priority is used to generate a reasonable priority value in terms of the
    size of the payload to be stored. The size is binned, roughly corresponding to
    1kb, 10kb, 100kb, 1mb, etc., and the *largest* sized items are evicted first.
    Within the same bin, the *oldest* items (with respect to timestamp at insertion time)
    are evicted first. This is intended to safely allow relatively large `maxsize`
    values, as many samples may be small; and ensure that the larger items do not
    monopolize the RAM of the running service.
    """
    keys: PriorityQueue[tuple[float, tuple[str, str]]]
    cache: dict[tuple[str, str], tuple[bytes, BitMaskFeatureNames]]
    byte_sizes: dict[tuple[str, str], int]
    mb_limit: int

    def __init__(self):
        v = 'DATABASE_DOWNLOAD_CACHE_SAMPLE_LIMIT'
        if v in os_environ:
            limit = int(os_environ[v])
        else:
            limit = 1000
            logger.warning(f"Set {v} (to limit the RAM usage of the ondemand service's cache via limiting the number of cached items), using default: {limit}")
        self.keys = PriorityQueue(maxsize=limit)
        self.cache = {}
        self.byte_sizes = {}
        v = 'DATABASE_DOWNLOAD_CACHE_LIMIT_MB'
        if v in os_environ:
            mb_limit = int(os_environ[v])
        else:
            mb_limit = 500
            logger.warning(f"Set {v} (to limit the RAM usage of the ondemand service's cache), using default: {mb_limit}")
        self.mb_limit = mb_limit

    def has(self, study: str, sample: str) -> bool:
        return (study, sample) in self.cache

    def retrieve(self, study: str, sample: str) -> tuple[bytes, BitMaskFeatureNames]:
        return self.cache[(study, sample)]

    def consider_insertion(self, study: str, sample: str, value: tuple[bytes, BitMaskFeatureNames]) -> bool:
        if self.has(study, sample):
            return
        byte_size = len(value[0])
        self.byte_sizes[(study, sample)] = byte_size
        self._insert(study, sample, value, self._determine_priority(byte_size))

    def _insert(self, study: str, sample: str, value: tuple[bytes, BitMaskFeatureNames], priority: CellDataPriority) -> bool:
        self._enforce_mb_limit()
        if self.keys.full():
            self._pop_one_item()
        self._insert_item(study, sample, value, priority)

    def _enforce_mb_limit(self) -> None:
        total = self._total_mb_estimate()
        count = 0
        while self._total_mb_estimate() > self.mb_limit and not self.keys.empty():
            self._pop_one_item()
            count += 1
        new_total = self._total_mb_estimate()
        if new_total != total:
            logger.info(f'Enforced cache limit {self.mb_limit}MB: From {total}MB down to {new_total}MB by evicting {count} items.')

    def _total_mb_estimate(self):
        return int(sum(self.byte_sizes.values()) / 1000000)

    def _pop_one_item(self) -> None:
        priority, (study, sample) = self.keys.get()
        del self.cache[(study, sample)]
        del self.byte_sizes[(study, sample)]

    def _insert_item(self, study: str, sample: str, value: tuple[bytes, BitMaskFeatureNames], priority: CellDataPriority) -> None:
        self.keys.put((priority, (study, sample)))
        self.cache[(study, sample)] = value

    @staticmethod
    def _determine_priority(size_bytes: int) -> CellDataPriority:
        binned = 1 + int(log10(size_bytes / 1000))
        return (-binned, int(time()))
