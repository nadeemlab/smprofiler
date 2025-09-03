"""Constants referring to canonical graph plugins."""

from enum import Enum
from enum import auto
from itertools import product

CG_GNN_ALIASES = ('cg-gnn', 'cggnn', 'cgnn')

_graph_aliases = ('graph', 'gnn')
_separators = (' ', '-', '')
_transformer_aliases = ('transformer', 'transforms', 'transform', 't')
graph_transformer_aliases = set(
    ''.join(combination) for combination in
    product(_graph_aliases, _separators, _transformer_aliases)
)
graph_transformer_aliases.add('tmi2022')
GRAPH_TRANSFORMER_ALIASES = tuple(graph_transformer_aliases)


class GNNPlugin(str, Enum):
    CGGNN = 'cg-gnn'
    GRAPH_TRANSFORMER = 'graph-transformer'


PLUGIN_ALIASES = {
    GNNPlugin.CGGNN.value: CG_GNN_ALIASES,
    GNNPlugin.GRAPH_TRANSFORMER.value: graph_transformer_aliases,
}
