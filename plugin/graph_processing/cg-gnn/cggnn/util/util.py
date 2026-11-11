"""Cell/tissue graph dataset utility functions."""

from os.path import join
from importlib import import_module
from copy import deepcopy
from random import seed
from typing import Tuple, List, Dict, Any, Optional, Iterable, Literal, NamedTuple, Sequence

from numpy import loadtxt
from numpy.random import seed as np_seed
from torch import Tensor, LongTensor, IntTensor, load, manual_seed, use_deterministic_algorithms  # type: ignore
from torch.cuda import is_available, manual_seed_all
from torch.cuda import manual_seed as cuda_manual_seed  # type: ignore
from torch.utils.data import ConcatDataset, DataLoader, SubsetRandomSampler
from torch.utils.data import Dataset
from torch.backends import cudnn  # type: ignore
from dgl import batch, DGLGraph  # type: ignore
from dgl import seed as dgl_seed  # type: ignore
from dgl.data.utils import (  # type: ignore
    save_graphs,  # type: ignore
    save_info,  # type: ignore
    load_graphs,  # type: ignore
    load_info,  # type: ignore
)
from sklearn.model_selection import KFold

from cggnn.util.ml.cell_graph_model import CellGraphModel
from cggnn.util.constants import DEFAULT_GNN_PARAMETERS, DEFAULT_CLASSIFICATION_PARAMETERS, FEATURES


IS_CUDA = is_available()
DEVICE = 'cuda:0' if IS_CUDA else 'cpu'
COLLATE_USING = {
    'DGLGraph': batch,
    'DGLHeteroGraph': batch,
    'Tensor': lambda x: x,
    'int': lambda x: IntTensor(x).to(DEVICE),
    'int64': lambda x: IntTensor(x).to(DEVICE),
    'float': lambda x: LongTensor(x).to(DEVICE)
}

SETS_type = Literal['train', 'validation', 'test']


def load_label_to_result(path: str) -> dict[int, str]:
    """Read in label_to_result JSON."""
    return {int(label): result for label, result in json_load(
        open(path, encoding='utf-8')).items()}


class GraphData(NamedTuple):
    """Data relevant to a cell graph instance."""
    graph: DGLGraph
    label: int | None
    name: str
    specimen: str
    set: SETS_type | None


class GraphMetadata(NamedTuple):
    """Data relevant to a cell graph instance."""
    name: str
    specimen: str
    set: SETS_type | None


def save_cell_graphs(graphs_data: list[GraphData], output_directory: str) -> None:
    """Save cell graphs to a directory."""
    graphs: list[DGLGraph] = []
    labels: list[int] = []
    metadata: list[GraphMetadata] = []
    unlabeled_graphs: list[DGLGraph] = []
    unlabeled_metadata: list[GraphMetadata] = []
    for graph_data in graphs_data:
        if graph_data.label is not None:
            graphs.append(graph_data.graph)
            metadata.append(GraphMetadata(
                graph_data.name,
                graph_data.specimen,
                graph_data.set,
            ))
            labels.append(graph_data.label)
        else:
            unlabeled_graphs.append(graph_data.graph)
            unlabeled_metadata.append(GraphMetadata(
                graph_data.name,
                graph_data.specimen,
                graph_data.set,
            ))
    _save_dgl_graphs(
        output_directory,
        graphs + unlabeled_graphs,
        metadata + unlabeled_metadata,
        labels,
    )


def _save_dgl_graphs(
    output_directory: str,
    graphs: list[DGLGraph],
    metadata: list[GraphMetadata],
    labels: list[int],
) -> None:
    """Save DGL cell graphs to a directory."""
    save_graphs(join(output_directory, 'graphs.bin'),
                graphs,
                {'labels': IntTensor(labels)})
    save_info(join(output_directory, 'graph_info.pkl'), {'info': metadata})


def load_cell_graphs(graph_directory: str) -> tuple[list[GraphData], list[str]]:
    """Load cell graph information from a directory.

    Assumes directory contains the files `graphs.bin`, `graph_info.pkl`, and `feature_names.txt`.
    """
    graphs, labels, metadata = _load_dgl_graphs(graph_directory)
    graph_data: list[GraphData] = []
    for i, graph in enumerate(graphs):
        graph_data.append(GraphData(
            graph,
            labels[i] if i < len(labels) else None,
            metadata[i].name,
            metadata[i].specimen,
            metadata[i].set,
        ))
    feature_names: list[str] = loadtxt(
        join(graph_directory, 'feature_names.txt'),
        dtype=str,
        delimiter=',',
    ).tolist()
    return graph_data, feature_names


def _load_dgl_graphs(graph_directory: str) -> tuple[list[DGLGraph], list[int], list[GraphMetadata]]:
    """Load cell graphs saved as DGL files from a directory."""
    graphs, labels = load_graphs(join(graph_directory, 'graphs.bin'))
    graphs: list[DGLGraph]
    labels: dict[str, IntTensor]
    metadata: list[GraphMetadata] = load_info(join(graph_directory, 'graph_info.pkl'))['info']
    return graphs, labels['labels'].tolist(), metadata


class CGDataset(Dataset):
    """Cell graph dataset."""

    def __init__(
        self,
        cell_graphs: list[DGLGraph],
        cell_graph_labels: list[int] | None = None,
        load_in_ram: bool = False,
    ):
        """Cell graph dataset constructor.

        Args:
            cell_graphs: list[DGLGraph]
                Cell graphs for a given split (e.g., test).
            cell_graph_labels: list[int] | None
                Labels for the cell graphs. Optional.
            load_in_ram: bool = False
                Whether to load the graphs in RAM. Defaults to False.
        """
        super(CGDataset, self).__init__()

        self.cell_graphs = cell_graphs
        self.cell_graph_labels = cell_graph_labels
        self.n_cell_graphs = len(self.cell_graphs)
        self.load_in_ram = load_in_ram

    def __getitem__(self, index: int) -> DGLGraph | tuple[DGLGraph, float]:
        """Get an example.

        Args:
            index (int): index of the example.
        """
        cell_graph = self.cell_graphs[index]
        if IS_CUDA:
            cell_graph = cell_graph.to('cuda:0')
        return cell_graph if (self.cell_graph_labels is None) \
            else (cell_graph, float(self.cell_graph_labels[index]))

    def __len__(self):
        """Return the number of samples in the dataset."""
        return self.n_cell_graphs


def create_datasets(
    graphs_data: list[GraphData],
    in_ram: bool = True,
    k_folds: int = 3,
) -> tuple[CGDataset, CGDataset | None, CGDataset | None, KFold | None]:
    """Make the cell and/or tissue graph datasets and the k-fold if necessary."""
    cell_graph_sets = split_graph_sets(graphs_data)
    train_dataset: CGDataset | None = \
        create_dataset(cell_graph_sets[0][0], cell_graph_sets[0][1], in_ram)
    assert train_dataset is not None
    validation_dataset = create_dataset(cell_graph_sets[1][0], cell_graph_sets[1][1], in_ram)
    test_dataset = create_dataset(cell_graph_sets[2][0], cell_graph_sets[2][1], in_ram)

    if (k_folds > 0) and (validation_dataset is not None):
        # stack train and validation datasets if both exist and k-fold cross validation is on
        train_dataset = ConcatDataset((train_dataset, validation_dataset))
        validation_dataset = None
    elif (k_folds == 0) and (validation_dataset is None):
        # set k_folds to 3 if not provided and no validation data is provided
        k_folds = 3
    kfold = KFold(n_splits=k_folds, shuffle=True) if k_folds > 0 else None

    return train_dataset, validation_dataset, test_dataset, kfold


def create_dataset(
    cell_graphs: list[DGLGraph],
    cell_graph_labels: list[int] | None = None,
    in_ram: bool = True,
) -> CGDataset | None:
    """Make a cell graph dataset."""
    return CGDataset(cell_graphs, cell_graph_labels, load_in_ram=in_ram) \
        if (len(cell_graphs) > 0) else None


def create_training_dataloaders(
    train_ids: Sequence[int] | None,
    test_ids: Sequence[int] | None,
    train_dataset: CGDataset,
    validation_dataset: CGDataset | None,
    batch_size: int,
) -> tuple[DataLoader, DataLoader]:
    """Determine whether to k-fold and then create dataloaders."""
    if (train_ids is None) or (test_ids is None):
        if validation_dataset is None:
            raise ValueError("validation_dataset must exist.")
        train_dataloader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            collate_fn=collate,
        )
        validation_dataloader = DataLoader(
            validation_dataset,
            batch_size=batch_size,
            shuffle=True,
            collate_fn=collate,
        )
    else:
        if validation_dataset is not None:
            raise ValueError(
                "validation_dataset provided but k-folding of training dataset requested."
            )
        train_subsampler = SubsetRandomSampler(train_ids)
        test_subsampler = SubsetRandomSampler(test_ids)
        train_dataloader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            sampler=train_subsampler,
            collate_fn=collate,
        )
        validation_dataloader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            sampler=test_subsampler,
            collate_fn=collate,
        )

    return train_dataloader, validation_dataloader


def collate(example_batch: Tensor) -> tuple[tuple, LongTensor]:
    """Collate a batch.

    Args:
        example_batch (torch.tensor): a batch of examples.
    Returns:
        data: (tuple)
        labels: (torch.LongTensor)
    """
    if isinstance(example_batch[0], tuple):  # graph and label
        def collate_fn(batch, id, type):
            return COLLATE_USING[type]([example[id] for example in batch])
        num_modalities = len(example_batch[0])
        return tuple([
            collate_fn(example_batch, mod_id, type(example_batch[0][mod_id]).__name__)
            for mod_id in range(num_modalities)
        ])
    else:  # graph only
        return tuple([COLLATE_USING[type(example_batch[0]).__name__](example_batch)])


def split_graph_sets(graphs_data: list[GraphData]) -> tuple[
    tuple[list[DGLGraph], list[int]],
    tuple[list[DGLGraph], list[int]],
    tuple[list[DGLGraph], list[int]],
    list[DGLGraph],
]:
    """Split graph data list into train, validation, test, and unlabeled sets."""
    cg_train: tuple[list[DGLGraph], list[int]] = ([], [])
    cg_val: tuple[list[DGLGraph], list[int]] = ([], [])
    cg_test: tuple[list[DGLGraph], list[int]] = ([], [])
    cg_unlabeled: list[DGLGraph] = []
    for gd in graphs_data:
        if gd.label is None:
            cg_unlabeled.append(gd.graph)
            continue
        which_set: tuple[list[DGLGraph], list[int]] = cg_train
        if gd.set == 'validation':
            which_set = cg_val
        elif gd.set == 'test':
            which_set = cg_test
        which_set[0].append(gd.graph)
        which_set[1].append(gd.label)
    return cg_train, cg_val, cg_test, cg_unlabeled


def instantiate_model(cell_graphs: List[GraphData],
                      gnn_parameters: Dict[str, Any] = DEFAULT_GNN_PARAMETERS,
                      classification_parameters: Dict[str,
                                                      Any] = DEFAULT_CLASSIFICATION_PARAMETERS,
                      model_checkpoint_path: Optional[str] = None
                      ) -> CellGraphModel:
    """Return a model set up as specified."""
    model = CellGraphModel(
        gnn_params=gnn_parameters,
        classification_params=classification_parameters,
        node_dim=cell_graphs[0].graph.ndata[FEATURES].shape[1],
        num_classes=int(max(g.label for g in cell_graphs))+1
    ).to(DEVICE)
    if model_checkpoint_path is not None:
        model.load_state_dict(load(model_checkpoint_path))
    return model


def dynamic_import_from(source_file: str, class_name: str) -> Any:
    """Import class_name from source_file dynamically.

    Args:
        source_file (str): Where to import from
        class_name (str): What to import

    Returns:
        Any: The class to be imported
    """
    module = import_module(source_file)
    return getattr(module, class_name)


def signal_last(input_iterable: Iterable[Any]) -> Iterable[Tuple[bool, Any]]:
    """Signal the last element of an iterable."""
    iterable = iter(input_iterable)
    return_value = next(iterable)
    for value in iterable:
        yield False, return_value
        return_value = value
    yield True, return_value


def copy_graph(x):
    """Copy a graph."""
    return deepcopy(x)


def torch_to_numpy(x):
    """Convert a torch tensor to a numpy array."""
    return x.cpu().detach().numpy()


def set_seeds(random_seed: int) -> None:
    """Set random seeds for all libraries."""
    seed(random_seed)
    np_seed(random_seed)
    manual_seed(random_seed)
    dgl_seed(random_seed)
    cuda_manual_seed(random_seed)
    manual_seed_all(random_seed)  # multi-GPU
    # use_deterministic_algorithms(True)
    # # multi_layer_gnn uses nondeterministic algorithm when on GPU
    # cudnn.deterministic = True
    cudnn.benchmark = False
