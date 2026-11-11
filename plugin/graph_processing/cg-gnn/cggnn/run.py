"""Functions that run key pipelines of the cggnn model."""

from typing import Dict, List, DefaultDict, Tuple, Optional
from os.path import join

from pandas import DataFrame
from dgl import DGLGraph  # type: ignore

from cggnn import train, calculate_importance, unify_importance_across, save_importances, \
    calculate_separability
from cggnn.util import GraphData, load_cell_graphs, save_cell_graphs, instantiate_model, \
    load_label_to_result, CellGraphModel


def train_and_evaluate(cg_directory: str,
                       in_ram: bool = False,
                       batch_size: int = 1,
                       epochs: int = 10,
                       learning_rate: float = 1e-3,
                       k_folds: int = 0,
                       explainer: Optional[str] = None,
                       merge_rois: bool = False,
                       random_seed: Optional[int] = None,
                       ) -> Tuple[CellGraphModel, List[GraphData], Optional[Dict[int, float]]]:
    """Train a CG-GNN on pre-split sets of cell graphs and explain it if requested."""
    graphs_data = load_cell_graphs(cg_directory)[0]
    model = train(graphs_data,
                  cg_directory,
                  in_ram=in_ram,
                  epochs=epochs,
                  learning_rate=learning_rate,
                  batch_size=batch_size,
                  k_folds=k_folds,
                  random_seed=random_seed)
    hs_id_to_importance: Optional[Dict[int, float]] = None
    if explainer is not None:
        cell_graphs = calculate_importance([d.graph for d in graphs_data],
                                           model,
                                           explainer,
                                           random_seed=random_seed)
        graphs_data = [d._replace(graph=graph) for d, graph in zip(graphs_data, cell_graphs)]
        save_cell_graphs(graphs_data, cg_directory)
        if merge_rois:
            cell_graphs_by_specimen: Dict[str, List[DGLGraph]] = DefaultDict(list)
            for cg in graphs_data:
                cell_graphs_by_specimen[cg.specimen].append(cg.graph)
            hs_id_to_importance = unify_importance_across(
                list(cell_graphs_by_specimen.values()),
                model,
                random_seed=random_seed)
            save_importances(hs_id_to_importance, join(cg_directory, 'importances.csv'))
    return model, graphs_data, hs_id_to_importance


def find_separability(cg_path: str,
                      model_checkpoint_path: str,
                      label_to_result_path: Optional[str] = None,
                      prune_misclassified: bool = False,
                      output_directory: Optional[str] = None,
                      random_seed: Optional[int] = None,
                      ) -> Tuple[DataFrame,
                                 DataFrame,
                                 Dict[Tuple[int, int] | Tuple[str, str], DataFrame]]:
    """Calculate separability scores for a cell graph dataset."""
    graphs_data, feature_names = load_cell_graphs(cg_path)
    df_concept, df_aggregated, dfs_k_dist = calculate_separability(
        graphs_data,
        instantiate_model(graphs_data, model_checkpoint_path=model_checkpoint_path),
        feature_names,
        label_to_result=load_label_to_result(label_to_result_path)
        if label_to_result_path else None,
        prune_misclassified=prune_misclassified,
        out_directory=output_directory,
        random_seed=random_seed)
    print(df_concept)
    print(df_aggregated)
    for cg_pair, df_k in dfs_k_dist.items():
        print(cg_pair)
        print(df_k)
    return df_concept, df_aggregated, dfs_k_dist
