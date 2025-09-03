#!/usr/bin/env python3
"""Train a model."""

from sys import path
from configparser import ConfigParser
from warnings import warn
from os import makedirs
from os.path import join
from subprocess import run
from typing import DefaultDict

from numpy import mean
from scipy.sparse import coo_matrix
from torch import from_numpy, tensor, long, float as torch_float, Size, sparse_coo_tensor, save, \
    load, sum, stack, mm
from torch.cuda import is_available
from torch.nn.functional import softmax
from pandas import Series
from tqdm import tqdm

path.append('/app')  # noqa
from tmi2022.main import main
from train_cli import parse_arguments, DEFAULT_CONFIG_FILE
from util import GraphData, load_hs_graphs, save_hs_graphs

TMP_DIRECTORY = 'tmp'


def _translate_smprofiler_graphs(smprofiler_graphs: list[GraphData], output_directory: str,
                          ) -> tuple[int, int, str, str, str, str]:
    """Translate the SMProfiler graphs into tmi2022 graphs."""
    makedirs(output_directory, exist_ok=True)
    ids_train: list[str] = []
    ids_val: list[str] = []
    ids_test: list[str] = []
    ids_unlabeled: list[str] = []
    for graph_data in smprofiler_graphs:
        graph_id = _convert_graph_to_tmi2022(graph_data, output_directory)
        match graph_data.set:
            case 'train':
                ids_train.append(graph_id)
            case 'validation':
                ids_val.append(graph_id)
            case 'test':
                ids_test.append(graph_id)
            case None:
                ids_unlabeled.append(graph_id)
            case _:
                raise ValueError(f'Unknown set {graph_data.set}')
    path_to_train_ids: str = join(output_directory, 'train_set.txt')
    path_to_val_ids: str = join(output_directory, 'validation_set.txt')
    path_to_test_ids: str = join(output_directory, 'test_set.txt')
    path_to_unlabeled_ids: str = join(output_directory, 'unlabeled_set.txt')
    with open(path_to_train_ids, 'w', encoding='utf-8') as f:
        f.write('\n'.join(ids_train))
    with open(path_to_val_ids, 'w', encoding='utf-8') as f:
        f.write('\n'.join(ids_val))
    with open(path_to_test_ids, 'w', encoding='utf-8') as f:
        f.write('\n'.join(ids_test))
    with open(path_to_unlabeled_ids, 'w', encoding='utf-8') as f:
        f.write('\n'.join(ids_unlabeled))

    # Find the number of classes
    unique_labels: set[int] = set()
    for graph_data in smprofiler_graphs:
        if graph_data.label is not None:
            unique_labels.add(graph_data.label)
    n_classes = len(unique_labels)
    assert unique_labels == set(range(len(unique_labels))), \
        "Labels are not zero-indexed and non-missing"
    n_features = smprofiler_graphs[0].graph.node_features.shape[1]

    return n_classes, n_features, \
        path_to_train_ids, path_to_val_ids, path_to_test_ids, path_to_unlabeled_ids


def _convert_graph_to_tmi2022(graph_data: GraphData, data_directory: str) -> str:
    """Convert an SMProfiler graph to a tmi2022 graph."""
    # Extract data from the GraphData instance
    adj = graph_data.graph.adj
    node_features = graph_data.graph.node_features
    centroids = graph_data.graph.centroids
    histological_structure_ids = graph_data.graph.histological_structure_ids
    label = graph_data.label
    name = graph_data.name
    specimen = graph_data.specimen

    # Convert the adjacency matrix to a PyTorch tensor
    adj = coo_matrix(adj)
    indices = tensor([adj.row, adj.col], dtype=long)
    values = tensor(adj.data, dtype=torch_float)
    shape = Size(adj.shape)
    adj_s = sparse_coo_tensor(indices, values, shape)

    # Convert the node features to a PyTorch tensor
    features = from_numpy(node_features)
    centroids = from_numpy(centroids)
    histological_structure_ids = from_numpy(histological_structure_ids)

    # Create the directory structure
    graph_path = join(data_directory, f'{specimen}_features', 'simclr_files', name)
    makedirs(graph_path, exist_ok=True)

    # Save the tensors to disk
    save(features, join(graph_path, 'features.pt'))
    save(adj_s, join(graph_path, 'adj_s.pt'))
    save(centroids, join(graph_path, 'centroids.pt'))
    save(histological_structure_ids, join(graph_path, 'histological_structure_ids.pt'))

    # Return the id and label in the format expected by GraphDataset
    return f'{specimen}/{name}\t{label}'


def run_tmi2022(n_class: int,
                n_features: int,
                data_path: str,
                val_set: str,
                train: bool,
                train_set: str | None = None,
                model_path: str = join(TMP_DIRECTORY, "saved_models"),
                log_path: str = join(TMP_DIRECTORY, "runs"),
                task_name: str = "GraphCAM",
                batch_size: int = 8,
                log_interval_local: int = 6,
                resume: str = "../graph_transformer/saved_models/GraphCAM.pth",
                ) -> None:
    """Train or test tmi2022 (the latter for creating GraphCAM ratings)."""

    # Set the CUDA_VISIBLE_DEVICES environment variable
    if not is_available():
        raise ValueError("A CUDA-supporting GPU is required.")

    # Call the main function with the appropriate parameters
    if train:
        assert train_set is not None
        main(n_class,
             n_features,
             data_path,
             model_path,
             log_path,
             task_name,
             batch_size,
             log_interval_local,
             train_set,
             val_set,
             train=True)
    else:  # test
        if val_set.endswith('.txt'):  # test, no graphcam
            main(n_class,
                 n_features,
                 data_path,
                 model_path,
                 log_path,
                 task_name,
                 batch_size,
                 log_interval_local,
                 val_set=val_set,
                 test=True,
                 resume=resume)
        else:  # we're finding graphcam for one graph
            id_txt = write_one_id_to_file(val_set)
            main(n_class,
                 n_features,
                 data_path,
                 model_path,
                 log_path,
                 task_name,
                 batch_size,
                 log_interval_local,
                 val_set=id_txt,
                 test=True,
                 graphcam=True,
                 resume=resume)


def write_one_id_to_file(val_set: str) -> str:
    """Write val_set to a txt file in TMP_DIRECTORY and return the file path."""
    file_path = join(TMP_DIRECTORY, 'id.txt')
    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(val_set)
    return file_path


# def _convert_from_graphdataset_format(id: str,
#                                       data_directory: str,
#                                       importances: NDArray[float_],) -> GraphData:
#     """Convert a tmi2022 graph of id to an SMProfiler graph."""
#     specimen, name = id.split('/')

#     # Load the tensors from disk
#     graph_path = join(data_directory, f'{specimen}_features', 'simclr_files', name)
#     features = load(join(graph_path, 'features.pt')).numpy()
#     adj_s = load(join(graph_path, 'adj_s.pt')).to_dense().numpy()
#     centroids = load(join(graph_path, 'centroids.pt')).numpy()
#     histological_structure_ids = load(join(graph_path, 'histological_structure_ids.pt')).numpy()

#     # Convert the adjacency matrix back to a sparse matrix
#     adj = csr_matrix(adj_s)

#     # Extract the label from the id
#     label = int(id.split('\t')[1])

#     # Create a GraphData instance
#     return GraphData(HSGraph(adj, features, centroids, histological_structure_ids, importances),
#                      label, name, specimen, None)


def _handle_random_seed_values(random_seed_value: str | None) -> int | None:
    if (random_seed_value is not None) and (str(random_seed_value).strip().lower() != "none"):
        return int(random_seed_value)
    return None


if __name__ == '__main__':
    args = parse_arguments()
    config_file = ConfigParser()
    config_file.read(args.config_file)
    random_seed: int | None = None
    if 'general' in config_file:
        random_seed = _handle_random_seed_values(config_file['general'].get('random_seed', None))
    if 'graph-transformer' not in config_file:
        warn('No cg-gnn section in config file. Using default values.')
        config_file.read(DEFAULT_CONFIG_FILE)
    config = config_file['graph-transformer']

    # Parse config file
    task_name = config.get('task_name', 'GraphCAM')
    batch_size = config.getint('batch_size', 8)
    log_interval_local = config.getint('log_interval_local', 6)

    smprofiler_graphs, _ = load_hs_graphs(args.input_directory)

    # Call the function with the current args.input_directory and graph_directory
    graph_directory = join(TMP_DIRECTORY, 'graphs')
    n_classes, n_features, path_to_train_ids, path_to_val_ids, path_to_test_ids, \
        path_to_unlabeled_ids = _translate_smprofiler_graphs(smprofiler_graphs, graph_directory)
    # Consider deleting smprofiler_graphs and reloading later to save memory

    # Train tmi2022
    run_tmi2022(n_classes,
                n_features,
                graph_directory,
                path_to_val_ids,
                True,
                train_set=path_to_train_ids,
                model_path=args.output_directory,
                log_path=TMP_DIRECTORY,
                task_name=task_name,
                batch_size=batch_size,
                log_interval_local=log_interval_local,
                )

    # Report test results
    run_tmi2022(n_classes,
                n_features,
                graph_directory,
                path_to_test_ids,
                False,
                model_path=args.output_directory,
                log_path=TMP_DIRECTORY,
                task_name=task_name,
                batch_size=1,
                log_interval_local=log_interval_local,
                resume=join(args.output_directory, f'{task_name}.pth'),
                )

    # Find the importance scores
    importance_scores: dict[int, list[float]] = DefaultDict(list)
    with open(path_to_test_ids, 'r', encoding='utf-8') as f:
        test_ids = f.read().splitlines()
    with open(path_to_val_ids, 'r', encoding='utf-8') as f:
        val_ids = f.read().splitlines()
    with open(path_to_train_ids, 'r', encoding='utf-8') as f:
        train_ids = f.read().splitlines()
    for single_id in tqdm(test_ids + val_ids + train_ids):
        run_tmi2022(n_classes,
                    n_features,
                    graph_directory,
                    single_id,
                    False,
                    model_path=args.output_directory,
                    log_path=TMP_DIRECTORY,
                    task_name=task_name,
                    batch_size=1,
                    log_interval_local=1,
                    resume=join(args.output_directory, f'{task_name}.pth'),
                    )

        # Load the CAM scores and convert them into an importance vector
        cams = [load(join('graphcam', f'cam_{i}.pt')).detach().cpu() for i in range(n_classes)]
        unified_cam = sum(stack(cams), dim=0)
        assign_matrix = load(join('graphcam', 's_matrix_ori.pt')).detach().cpu()
        assign_matrix = softmax(assign_matrix, dim=1)
        node_importance = mm(assign_matrix, unified_cam.transpose(1, 0))
        node_importance = node_importance.flatten().numpy()

        # Save the importance vector back to the graph in GraphData format
        for graph_data in smprofiler_graphs:
            if graph_data.name == single_id.split('\t')[0].split('/')[1]:
                assert graph_data.graph.node_features.shape[0] == node_importance.shape[0]
                graph_data.graph.importances = node_importance
                for i, importance in enumerate(node_importance):
                    importance_scores[graph_data.graph.histological_structure_ids[i]].append(
                        importance)
                break
        else:
            raise RuntimeError(f'Couldn\'t find graph associated with {single_id}')

    save_hs_graphs(smprofiler_graphs, args.output_directory)
    hs_id_to_importance: dict[int, float] = {k: mean(v) for k, v in importance_scores.items()}
    s = Series(hs_id_to_importance).sort_index()
    s.name = 'importance'
    s.to_csv(join(args.output_directory, 'importances.csv'))
