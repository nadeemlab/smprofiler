"""
Explain a cell graph (CG) prediction using a pretrained CG-GNN and a graph explainer.

As used in:
"Quantifying Explainers of Graph Neural Networks in Computational Pathology",
    Jaume et al, CVPR, 2021.
"""

from os import makedirs
from os.path import join
from itertools import combinations, compress
from re import sub
from typing import List, Optional, Tuple, Dict, Union, Any

from torch.cuda import is_available
from dgl import DGLGraph
from sklearn.preprocessing import minmax_scale
from sklearn.metrics import auc
from numpy import (empty, argsort, array, max, concatenate, reshape, histogram, corrcoef, mean,
                   ones, all, unique, sort, inf)
from numpy.typing import NDArray
from scipy.stats import wasserstein_distance
from scipy.ndimage.filters import uniform_filter1d
from pandas import DataFrame, Index
from matplotlib.pyplot import plot, title, savefig, legend, clf

from cggnn.util import GraphData
from cggnn.util.constants import FEATURES, IMPORTANCES
from cggnn.util import CellGraphModel
from cggnn.train import infer_with_model


IS_CUDA = is_available()
DEVICE = 'cuda:0' if IS_CUDA else 'cpu'


def calculate_separability(graphs_data: List[GraphData],
                           model: CellGraphModel,
                           feature_names: List[str],
                           label_to_result: Optional[Dict[int, str]] = None,
                           prune_misclassified: bool = True,
                           concept_grouping: Optional[Dict[str, List[str]]] = None,
                           risk: Optional[NDArray[Any]] = None,
                           pathological_prior: Optional[NDArray[Any]] = None,
                           out_directory: Optional[str] = None,
                           random_seed: Optional[int] = None
                           ) -> Tuple[DataFrame, DataFrame,
                                      Dict[Union[Tuple[int, int], Tuple[str, str]], DataFrame]]:
    """Generate separability scores for each concept."""
    # Get the importance scores, labels, and features from all cell graphs
    graphs: List[DGLGraph] = []
    importance_scores: List[NDArray] = []
    labels: List[int] = []
    features: List[NDArray] = []
    for g in graphs_data:
        if g.label is not None:
            graphs.append(g.graph)
            importance_scores.append(g.graph.ndata[IMPORTANCES])
            labels.append(g.label)
            features.append(g.graph.ndata[FEATURES])
    assert features[0].shape[1] == len(feature_names)

    classes = sort(unique(labels)).tolist()
    if max(labels) + 1 != len(classes):
        raise ValueError('Class missing from assigned labels. Ensure that your labels are '
                         'zero-indexed and that at least one example from every class is present '
                         'in your dataset.')

    # Fetch graph concepts and classes/labels
    if risk is None:
        risk = ones(len(classes)) / len(classes)
    else:
        assert len(risk) == len(classes)

    if prune_misclassified:
        mask = _misclassified([g.graph for g in graphs_data], labels, model, random_seed)
        importance_scores = list(compress(importance_scores, mask))
        features = list(compress(features, mask))
        labels = list(compress(labels, mask))

    # Compute separability scores
    least_cells = features[0].shape[0]
    for graph_attribute in features:
        if graph_attribute.shape[0] < least_cells:
            least_cells = graph_attribute.shape[0]
    separability_calculator = AttributeSeparability(
        classes, list(range(1, least_cells, max((1, round(least_cells/100))))))
    separability_scores, all_histograms, k_max_dist = separability_calculator.process(
        importance_list=importance_scores,
        attribute_list=features,
        label_list=labels,
        feature_names=feature_names
    )

    # Plot histograms
    if out_directory is not None:
        out_directory = join(out_directory, 'separability')
        makedirs(out_directory, exist_ok=True)
        for i, attribute_name in enumerate(feature_names):
            _plot_histogram(all_histograms, out_directory, i, attribute_name,
                            k=25 if 25 in all_histograms else max(tuple(all_histograms.keys())))

    # Compute final qualitative metrics
    if concept_grouping is None:
        # If not explicitly provided, each attribute will be its own concept
        concept_grouping = {cn: [cn] for cn in feature_names}
    metric_analyser = SeparabilityAggregator(
        separability_scores, concept_grouping)
    df_aggregated = DataFrame({
        'average': metric_analyser.compute_average_separability_score(risk),
        'maximum': metric_analyser.compute_max_separability_score(risk)
    })
    if pathological_prior is not None:
        df_aggregated['correlation'] = metric_analyser.compute_correlation_separability_score(
            risk, pathological_prior)
    if all(risk == risk[0]):
        df_aggregated.drop('agg_with_risk', axis=0, inplace=True)

    dfs_k_max_distance: Dict[Tuple[int, int], DataFrame] = {}
    for class_pair, k_data in k_max_dist.items():
        dfs_k_max_distance[class_pair] = DataFrame(
            {'k': [dat[0] for dat in k_data.values()],
             'dist': [dat[1] for dat in k_data.values()]},
            index=[feature_names[i] for i in k_data.keys()])

    df_seperability_by_concept = DataFrame(metric_analyser.separability_scores)

    if label_to_result is not None:
        df_seperability_by_concept.columns = [
            _class_pair_rephrase(class_pair, label_to_result) for class_pair in
            df_seperability_by_concept.columns.values]
        df_aggregated.set_index(Index(
            (_class_pair_rephrase(class_pair, label_to_result)
             if isinstance(class_pair, tuple) else class_pair
             ) for class_pair in df_aggregated.index.values), inplace=True)
        dfs_k_max_distance = {_class_pair_rephrase(
            class_pair, label_to_result): df for class_pair, df in dfs_k_max_distance.items()}

    return df_seperability_by_concept, df_aggregated, dfs_k_max_distance


class AttributeSeparability:
    """Process and show the separability between attributes in the model."""

    def __init__(
        self,
        classes: List[int],
        keep_nuclei: List[int] = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
    ) -> None:
        """Construct an instance of AttributeSeparability.

        Args:
            classes (List[int]): Classifications.
            keep_nuclei (List[int]): Number of nuclei to retain each time.
                                     Default to [5, 10, 15, 20, 25, 30, 35, 40, 45, 50].
        """
        self.keep_nuclei_list = keep_nuclei
        self.n_keep_nuclei = len(self.keep_nuclei_list)
        self.classes = classes
        self.n_classes = len(self.classes)
        self.class_pairs = list(combinations(self.classes, 2))
        self.n_class_pairs = len(self.class_pairs)

    def process(
        self,
        importance_list: List[NDArray],
        attribute_list: List[NDArray],
        label_list: List[int],
        feature_names: List[str]
    ) -> Tuple[Dict[Tuple[int, int], Dict[str, float]],
               Dict[int, Dict[int, NDArray]],
               Dict[Tuple[int, int], Dict[int, Tuple[int, float]]]]:
        """Derive metrics based on the explainer importance scores and nuclei-level concepts.

        Args:
            importance_list (List[NDArray]): Cell importance scores output by explainers.
            attribute_list (List[NDArray]): Cell-level attributes (later grouped into concepts).
            label_list (List[int]): Labels.
        """
        # 1. extract number of concepts
        n_attrs = attribute_list[0].shape[1]

        # 2. min max normalize the importance scores
        importance_list = self.normalize_node_importance(
            importance_list)

        # 3. extract all the histograms
        all_histograms = self._compute_attr_histograms(
            importance_list, attribute_list, label_list, n_attrs)

        # 4. compute the Wasserstein distance for all the class pairs
        all_distances = self._compute_hist_distances(all_histograms, n_attrs)

        # 5. compute the AUC over the #k: output will be Omega x #c
        # Addition: find the k-value with the max distance
        all_aucs: Dict[Tuple[int, int], Dict[str, float]] = {}
        k_max_dist: Dict[Tuple[int, int], Dict[int, Tuple[int, float]]] = {}
        for class_pair_id in range(self.n_class_pairs):
            all_aucs[self.class_pairs[class_pair_id]] = {}
            k_max_dist[self.class_pairs[class_pair_id]] = {}
            for attr_id in range(n_attrs):
                attr_name = feature_names[attr_id]
                all_aucs[self.class_pairs[class_pair_id]][attr_name] = auc(
                    array(self.keep_nuclei_list) /
                    max(self.keep_nuclei_list),
                    all_distances[:, class_pair_id, attr_id]
                )

                k_max = self.keep_nuclei_list[0]
                max_dist = all_distances[k_max, class_pair_id, attr_id]
                for i, k in enumerate(self.keep_nuclei_list):
                    dist = all_distances[i, class_pair_id, attr_id]
                    if dist > max_dist:
                        k_max = k
                        max_dist = dist
                k_max_dist[self.class_pairs[class_pair_id]
                           ][attr_id] = (k_max, max_dist)

        return all_aucs, all_histograms, k_max_dist

    def _compute_hist_distances(
        self,
        all_histograms: Dict,
        n_attr: int
    ) -> NDArray:
        """Compute all the pair-wise histogram distances.

        Args:
             all_histograms (Dict): all the histograms.
             n_concepts (int): number of concepts.
        """
        all_distances = empty(
            (self.n_keep_nuclei, self.n_class_pairs, n_attr))
        for k_id, k in enumerate(self.keep_nuclei_list):
            omega = 0
            for tx in range(self.n_classes):
                for ty in range(self.n_classes):
                    if tx < ty:
                        for attr_id in range(n_attr):
                            all_distances[k_id, omega, attr_id] = wasserstein_distance(
                                all_histograms[k][tx][attr_id],
                                all_histograms[k][ty][attr_id]
                            )
                        omega += 1
        return all_distances

    def _compute_attr_histograms(
        self,
        importance_list: List[NDArray],
        attribute_list: List[NDArray],
        label_list: List[int],
        n_attrs: int
    ) -> Dict[int, Dict[int, NDArray]]:
        """Compute histograms for all the attributes.

        Args:
            importance_list (List[NDArray]): Cell importance scores output by explainers.
            attribute_list (List[NDArray]): Cell-level attributes.
            label_list (List[int]): Labels.
        Returns:
            all_histograms (Dict[int, Dict[int, NDArray]]): Dict with all the histograms
                                                            for each thresh k (as key),
                                                            tumor type (as key) and
                                                            attributes (as np array).
        """
        all_histograms: Dict[int, Dict[int, NDArray]] = {}
        for k in self.keep_nuclei_list:
            all_histograms[k] = {}

            attrs = [c[argsort(s)[-k:]]
                     for c, s in zip(attribute_list, importance_list)]
            attrs = concatenate(attrs, axis=0)  # (#samples x k) x #attrs
            attrs[attrs == inf] = 0  # ensure no weird values in attributes
            attrs = minmax_scale(attrs)
            # #samples x k x #attrs
            attrs = reshape(attrs, (-1, k, n_attrs))
            attrs = list(attrs)

            for t in range(self.n_classes):

                # i. extract the samples of type t
                selected_attrs = [a for l, a in zip(
                    label_list, attrs) if l == t]
                if len(selected_attrs) == 0:
                    raise RuntimeError(f'Missing samples of class {t}')
                selected_attrs = concatenate(selected_attrs, axis=0)

                # iii. build the histogram for all the attrs (dim = #nuclei x attr_types)
                all_histograms[k][t] = array(
                    [self.build_hist(selected_attrs[:, attr_id])
                     for attr_id in range(selected_attrs.shape[1])]
                )
        return all_histograms

    @staticmethod
    def normalize_node_importance(node_importance: List[NDArray]) -> List[NDArray]:
        """Normalize node importance. Min-max normalization on each sample.

        Args:
            node_importance (List[NDArray]): node importance output by an explainer.
        Returns:
            node_importance (List[NDArray]): Normalized node importance.
        """
        node_importance = [minmax_scale(x) for x in node_importance]
        return node_importance

    @staticmethod
    def build_hist(concept_values: NDArray, num_bins: int = 100) -> NDArray:
        """Build a 1D histogram using the concept_values.

        Args:
            concept_values (NDArray): All the nuclei-level values for a concept.
            num_bins (int): Number of bins in the histogram. Default to 100.
        Returns:
            hist (NDArray): Histogram
        """
        hist, _ = histogram(
            concept_values, bins=num_bins, range=(0., 1.), density=True)
        return hist


class SeparabilityAggregator:
    """Aggregation of separability metrics."""

    def __init__(
        self,
        separability_scores: Dict[Tuple[int, int], Dict[str, float]],
        concept_grouping: Dict[str, List[str]]
    ) -> None:
        """Construct an instance of SeparabilityAggregator.

        Args:
            separability_score (Dict[Dict][float]): Separability score for all the class pairs
                                                    (as key) and attributes (as key).
        """
        self.separability_scores = self._group_separability_scores(
            separability_scores, concept_grouping)

    def _group_separability_scores(self,
                                   sep_scores: Dict[Tuple[int, int], Dict[str, float]],
                                   concept_grouping: Dict[str, List[str]]
                                   ) -> Dict[Tuple[int, int], Dict[str, float]]:
        """Group the individual attribute-wise separability scores according to the given concepts.

        Args:
            sep_scores (Dict[Tuple[int, int], Dict[str, float]]): Separability scores
        Returns:
            grouped_sep_scores (Dict[int, Dict[str, float]]): Grouped separability scores
        """
        grouped_sep_scores: Dict[Tuple[int, int], Dict[str, float]] = {}

        for class_pair, class_pair_val in sep_scores.items():
            grouped_sep_scores[class_pair] = {}
            for concept_key, concept_attrs in concept_grouping.items():
                val = sum([class_pair_val[attr]
                          for attr in concept_attrs]) / len(concept_attrs)
                grouped_sep_scores[class_pair][concept_key] = val
        return grouped_sep_scores

    def compute_max_separability_score(self, risk: NDArray) -> Dict[Union[Tuple[int, int], str],
                                                                    float]:
        """Compute max separability score for each class pair and aggregate w/ and w/o risk.

        Returns:
            max_sep_score (Dict[Union[Tuple[int, int], str], float]): Maximum separability score.
        """
        max_sep_score: Dict[Union[Tuple[int, int], str], float] = {}
        for class_pair, class_pair_val in self.separability_scores.items():
            max_sep_score[class_pair] = max(
                [val for _, val in class_pair_val.items()])
        max_sep_score['agg_with_risk'] = sum(
            array([val for _, val in max_sep_score.items()]) *
            risk
        )
        max_sep_score['agg'] = sum(
            [val for key, val in max_sep_score.items() if isinstance(key, tuple)])
        return max_sep_score

    def compute_average_separability_score(self, risk: NDArray) -> Dict[Union[Tuple[int, int],
                                                                              str], float]:
        """Compute average separability score for each class pair and aggregate w/ and w/o risk.

        Returns:
            avg_sep_score (Dict[Union[Tuple[int, int], str], float]): Average separability score.
        """
        avg_sep_score: Dict[Union[Tuple[int, int], str], float] = {}
        for class_pair, class_pair_val in self.separability_scores.items():
            avg_sep_score[class_pair] = mean(
                array([val for _, val in class_pair_val.items()]))
        avg_sep_score['agg_with_risk'] = sum(
            array([val for _, val in avg_sep_score.items()]) *
            risk
        )
        avg_sep_score['agg'] = sum(
            [val for key, val in avg_sep_score.items() if isinstance(key, tuple)])
        return avg_sep_score

    def compute_correlation_separability_score(self,
                                               risk: NDArray,
                                               pathological_prior: NDArray
                                               ) -> Dict[Union[Tuple[int, int], str], float]:
        """Compute correlation separability score between the prior and the concept-wise scores.

        Returns:
            corr_sep_score (Dict[Union[Tuple[int, int], str], float]): Correlation sep score.
        """
        sep_scores = DataFrame.from_dict(
            self.separability_scores).to_numpy()
        class_pairs = list(self.separability_scores.keys())
        sep_scores = minmax_scale(sep_scores)
        corrs: Dict[Union[Tuple[int, int], str], float] = {}
        for i_class_pair in range(sep_scores.shape[1]):
            corr_sep_score = corrcoef(
                pathological_prior[:, i_class_pair], sep_scores[:, i_class_pair])
            corrs[class_pairs[i_class_pair]] = corr_sep_score[1, 0]
        corrs['agg_with_risk'] = sum(
            array([val for _, val in corrs.items()]) *
            risk
        )
        corrs['agg'] = sum(
            [val for key, val in corrs.items() if isinstance(key, tuple)])
        return corrs


def _plot_histogram(all_histograms: Dict[int, Dict[int, NDArray]],
                    save_path: str,
                    attr_id: int,
                    attr_name: str,
                    k: int = 25,
                    smoothing: bool = True) -> None:
    """Create histogram for a single attribute."""
    x = array(list(range(100)))
    for i, histogram in all_histograms[k].items():
        plot(x, uniform_filter1d(
            histogram[attr_id], size=5) if smoothing else histogram[attr_id], label=f'Class {i}')

    title(attr_name)
    legend()
    savefig(join(save_path, sub(r'[^\w\-_\. ]', '', attr_name) + '.png'))
    clf()


def _misclassified(cell_graphs: List[DGLGraph],
                   cell_graph_labels: List[int],
                   model: CellGraphModel,
                   random_seed: Optional[int] = None
                   ) -> List[bool]:
    """Identify which samples are misclassified."""
    return (array(cell_graph_labels) == infer_with_model(model,
                                                         cell_graphs,
                                                         random_seed=random_seed)).tolist()


def _class_pair_rephrase(class_pair: Tuple[int, int],
                         label_to_result: Dict[int, str]) -> Tuple[str, str]:
    """Convert an int class pair to a tuple class pair."""
    return tuple(label_to_result[label] for label in class_pair)
