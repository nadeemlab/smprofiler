"""
Calculate importance scores per node in an ROI.

As used in:
"Quantifying Explainers of Graph Neural Networks in Computational Pathology",
    Jaume et al, CVPR, 2021.
"""

from typing import List, Optional, Dict, Tuple, DefaultDict

from tqdm import tqdm
from numpy import average
from torch import FloatTensor
from torch.cuda import is_available
from dgl import DGLGraph
from pandas import Series

from cggnn.util import CellGraphModel, set_seeds
from cggnn.util.constants import IMPORTANCES, INDICES
from cggnn.util.interpretability import (BaseExplainer, GraphLRPExplainer, GraphGradCAMExplainer,
                                         GraphGradCAMPPExplainer, GraphPruningExplainer)
from cggnn.train import infer_with_model

IS_CUDA = is_available()
DEVICE = 'cuda:0' if IS_CUDA else 'cpu'


def calculate_importance(cell_graphs: List[DGLGraph],
                         model: CellGraphModel,
                         explainer_model: str,
                         random_seed: Optional[int] = None
                         ) -> List[DGLGraph]:
    """Calculate the importance for all cells in every graph."""
    explainer: BaseExplainer
    explainer_model = explainer_model.lower().strip()
    if explainer_model in {'lrp', 'graphlrpexplainer'}:
        explainer = GraphLRPExplainer(model=model)
    elif explainer_model in {'cam', 'gradcam', 'graphgradcamexplainer'}:
        explainer = GraphGradCAMExplainer(model=model)
    elif explainer_model in {'pp', 'campp', 'gradcampp', 'graphgradcamppexplainer'}:
        explainer = GraphGradCAMPPExplainer(model=model)
    elif explainer_model in {'pruning', 'gnn', 'graphpruningexplainer'}:
        explainer = GraphPruningExplainer(model=model)
    else:
        raise ValueError("explainer_model not recognized.")

    if random_seed is not None:
        set_seeds(random_seed)

    # Set model to train so it'll let us do backpropogation.
    # This shouldn't be necessary since we don't want the model to change at all while running the
    # explainer. In fact, it isn't necessary when running the original histocartography code, but
    # in this version of python and torch, it results in a can't-backprop-in-eval error in torch
    # because calculating the weights requires backprop-ing to get the backward_hook.
    # TODO: Fix this.
    model = model.train()

    # Calculate the importance scores for every graph
    for graph in tqdm(cell_graphs):
        importance_scores, _ = explainer.process(graph.to(DEVICE))
        graph.ndata[IMPORTANCES] = FloatTensor(importance_scores)

    return cell_graphs


def unify_importance_across(graphs_by_specimen: List[List[DGLGraph]],
                            model: CellGraphModel,
                            random_seed: Optional[int] = None
                            ) -> Dict[int, float]:
    """Merge importance values for all cells in all ROIs in all specimens."""
    if random_seed is not None:
        set_seeds(random_seed)
    hs_id_to_importance: Dict[int, float] = {}
    for graphs in graphs_by_specimen:
        for hs_id, importance in _unify_importance(graphs, model).items():
            if hs_id in hs_id_to_importance:
                raise RuntimeError(
                    'The same histological structure ID appears in multiple specimens.')
            hs_id_to_importance[hs_id] = importance
    return hs_id_to_importance


def _unify_importance(graphs: List[DGLGraph], model: CellGraphModel) -> Dict[int, float]:
    """Merge the importance values for each cell in a specimen."""
    probs = infer_with_model(model, graphs, return_probability=True)
    hs_id_to_importances: Dict[int, List[Tuple[float, float]]] = DefaultDict(list)
    for i_graph, graph in enumerate(graphs):
        for i in range(graph.num_nodes()):
            hs_id_to_importances[graph.ndata[INDICES][i].item()].append(
                (graph.ndata[IMPORTANCES][i], max(probs[i_graph, ])))
    hs_id_to_importance: Dict[int, float] = {}
    for hs_id, importance_confidences in hs_id_to_importances.items():
        hs_id_to_importance[hs_id] = average([ic[0] for ic in importance_confidences],
                                             weights=[ic[1] for ic in importance_confidences])
    return hs_id_to_importance


def save_importances(hs_id_to_importance: Dict[int, float], out_directory: str) -> None:
    """Save importance scores per histological structure to CSV."""
    s = Series(hs_id_to_importance).sort_index()
    s.name = 'importance'
    s.to_csv(out_directory)
