from itertools import combinations
from itertools import product

from pandas import DataFrame

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class AtlasChannelInfoLogging:
    atlas_channels: list[str]
    identity: list[str]
    functional: list[str]

    def __init__(self, atlas_channels: list[str], identity: list[str], functional: list[str]) -> None:
        self.atlas_channels = atlas_channels
        self.identity = identity
        self.functional = functional

    def report_info(self):
        intersections = self._form_intersections_dataframe()
        logger.info('Overlaps between atlas channels and SMProfiler channels:')
        logger.info('\n' + intersections.to_string(index=False))
        differences = self._form_differences_dataframe()
        logger.info('Missing channels:')
        logger.info('\n' + differences.to_string(index=False))

    def _form_intersections_dataframe(self) -> DataFrame:
        combined_set = set(self.atlas_channels).union(self.identity).union(self.functional)
        set_pairs = tuple(combinations([
            ('', combined_set),
            ('atlas_channels', set(self.atlas_channels)),
            ('identity', set(self.identity)),
            ('functional', set(self.functional)),
        ], 2))
        intersection_records = []
        for (name1, set1), (name2, set2) in set_pairs:
            overlap = set1.intersection(set2)
            intersection_records.append((name1, name2, len(overlap)))
        return DataFrame(intersection_records, columns=['Channel set 1', 'Channel set 2', 'Overlap count'])

    def _form_differences_dataframe(self) -> DataFrame:
        groups = [
            ('atlas_channels', set(self.atlas_channels)),
            ('identity', set(self.identity)),
            ('functional', set(self.functional)),
        ]
        set_ordered_pairs = tuple(product(groups, groups))
        difference_records = []
        for (name1, set1), (name2, set2) in set_ordered_pairs:
            if name1 == name2:
                continue
            if set([name1, name2]) == set(['identity', 'functional']):
                continue
            difference = set1.difference(set2)
            small = sorted(list(difference))[0:min(10, len(difference))]
            examples = ', '.join(small)
            if len(small) < len(difference):
                examples = examples + ' ...'
            difference_records.append((name1, name2, len(difference), examples))
        differences = DataFrame(difference_records, columns=['Present in this set', 'but missing from', 'Missing count', 'Examples'])
        differences = differences[differences['Present in this set'] != '']
        return differences
