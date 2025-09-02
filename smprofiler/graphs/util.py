"""Histological structure graph dataset utility functions."""

from os import listdir, makedirs
from os.path import join
from json import load as json_load
from random import seed
from typing import NamedTuple, Literal
from dataclasses import dataclass, field

from numpy import (
    savetxt,  # type: ignore
    loadtxt,
    int_,
    float64,
)
from numpy.random import seed as np_seed
from numpy.typing import NDArray
from scipy.sparse import spmatrix, isspmatrix_csr, csr_matrix  # type: ignore
from h5py import File  # type: ignore

SETS = ('train', 'validation', 'test')
SETS_type = Literal['train', 'validation', 'test']


@dataclass
class HSGraph:
    """A histological structure graph instance."""
    adj: spmatrix
    node_features: NDArray[float64]
    centroids: NDArray[float64]
    histological_structure_ids: NDArray[int_]
    importances: NDArray[float64] | None = field(default=None)


class GraphData(NamedTuple):
    """Data relevant to a histological structure graph instance."""
    graph: HSGraph
    label: int | None
    name: str
    specimen: str
    set: SETS_type | None


def save_hs_graphs(graphs_data: list[GraphData], output_directory: str) -> None:
    """Save histological structure graphs to a directory.

    Saves the adjacency graph separately from the rest of the graph data for compatibility.
    """
    makedirs(output_directory, exist_ok=True)
    for gd in graphs_data:
        save_graph_data(gd, join(output_directory, f'{gd.name}.h5'))


def load_hs_graphs(graph_directory: str) -> tuple[list[GraphData], list[str]]:
    """Load histological structure graphs from a directory.

    Assumes directory contains the files `graphs.pkl`, `feature_names.txt`, and a sparse array for
    every graph in `graphs.pkl`.
    """
    graphs_data: list[GraphData] = []
    for filename in listdir(graph_directory):
        if filename.endswith('.h5'):
            try:
                graphs_data.append(load_graph_data(join(graph_directory, filename)))
            except KeyError:
                raise ValueError(f'Graph data file {filename} is missing required fields.')
    feature_names: list[str] = loadtxt(
        join(graph_directory, 'feature_names.txt'),
        dtype=str,
        delimiter=',',
    ).tolist()
    return graphs_data, feature_names


def save_graph_data(graph_data: GraphData, filename: str):
    """Save GraphData to an HDF5 file."""
    if not isspmatrix_csr(graph_data.graph.adj):
        raise ValueError('Graph adjacency matrix must be a CSR matrix.')

    with File(filename, 'w') as f:
        f.create_dataset('graph/adj/data', data=graph_data.graph.adj.data)
        f.create_dataset('graph/adj/indices', data=graph_data.graph.adj.indices)
        f.create_dataset('graph/adj/indptr', data=graph_data.graph.adj.indptr)
        f.create_dataset('graph/adj/shape', data=graph_data.graph.adj.shape)

        f.create_dataset('graph/node_features', data=graph_data.graph.node_features)
        f.create_dataset('graph/centroids', data=graph_data.graph.centroids)
        f.create_dataset(
            'graph/histological_structure_ids',
            data=graph_data.graph.histological_structure_ids,
        )
        if graph_data.graph.importances is not None:
            f.create_dataset('graph/importances', data=graph_data.graph.importances)

        f.create_dataset('label', data=graph_data.label)
        f.create_dataset('name', data=graph_data.name)
        f.create_dataset('specimen', data=graph_data.specimen)
        f.create_dataset('set', data=graph_data.set)


def load_graph_data(filename: str) -> GraphData:
    """Load GraphData from an HDF5 file."""
    with File(filename, 'r') as f:
        adj_data = f['graph/adj/data'][()]
        adj_indices = f['graph/adj/indices'][()]
        adj_indptr = f['graph/adj/indptr'][()]
        adj_shape = f['graph/adj/shape'][()]
        adj = csr_matrix((adj_data, adj_indices, adj_indptr), shape=adj_shape)

        node_features: NDArray[float64] = f['graph/node_features'][()]
        centroids: NDArray[float64] = f['graph/centroids'][()]
        histological_structure_ids: NDArray[int_] = f['graph/histological_structure_ids'][()]
        importances: NDArray[float64] = \
            f['graph/importances'][()] if 'graph/importances' in f else None

        # h5 files store strings as byte arrays
        label: int | None = f['label'][()]
        name: str = f['name'][()].decode()
        specimen: str = f['specimen'][()].decode()
        set: SETS_type = f['set'][()].decode()

    graph = HSGraph(adj, node_features, centroids, histological_structure_ids, importances)
    return GraphData(graph, label, name, specimen, set)


def save_graph_data_and_feature_names(
    graphs_data: list[GraphData],
    features_to_use: list[str],
    output_directory: str,
) -> None:
    """Save graph data and feature names to disk."""
    save_hs_graphs(graphs_data, output_directory)
    savetxt(join(output_directory, 'feature_names.txt'), features_to_use, fmt='%s', delimiter=',')


def load_label_to_result(path: str) -> dict[int, str]:
    """Read in label_to_result JSON."""
    return {int(label): result for label, result in json_load(
        open(path, encoding='utf-8')).items()}


def split_graph_sets(graphs_data: list[GraphData]) -> tuple[
    tuple[list[HSGraph], list[int]],
    tuple[list[HSGraph], list[int]],
    tuple[list[HSGraph], list[int]],
    list[HSGraph],
]:
    """Split graph data list into train, validation, test, and unlabeled sets."""
    cg_train: tuple[list[HSGraph], list[int]] = ([], [])
    cg_val: tuple[list[HSGraph], list[int]] = ([], [])
    cg_test: tuple[list[HSGraph], list[int]] = ([], [])
    cg_unlabeled: list[HSGraph] = []
    for gd in graphs_data:
        if gd.label is None:
            cg_unlabeled.append(gd.graph)
            continue
        which_set: tuple[list[HSGraph], list[int]] = cg_train
        if gd.set == 'validation':
            which_set = cg_val
        elif gd.set == 'test':
            which_set = cg_test
        which_set[0].append(gd.graph)
        which_set[1].append(gd.label)
    return cg_train, cg_val, cg_test, cg_unlabeled


def set_seeds(random_seed: int) -> None:
    """Set random seeds for all libraries."""
    seed(random_seed)
    np_seed(random_seed)
