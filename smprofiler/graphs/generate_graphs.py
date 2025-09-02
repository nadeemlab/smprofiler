"""Generates graphs from SMProfiler extracts."""

from os import makedirs
from os.path import join, exists
from random import shuffle, randint
from warnings import warn
from typing import DefaultDict

from numpy import (
    rint,
    median,
    prod,  # type: ignore
    argmax,
    int_,
)
from numpy.typing import NDArray
from sklearn.neighbors import KDTree, kneighbors_graph  # type: ignore
from pandas import DataFrame
from pandas.core.groupby.generic import DataFrameGroupBy
from tqdm import tqdm

from smprofiler.graphs.util import (
    SETS,
    SETS_type,
    HSGraph,
    GraphData,
    load_hs_graphs,
    save_graph_data_and_feature_names,
    set_seeds,
)

MIN_THRESHOLD_TO_CREATE_ROI = 0.1
BIG_SPECIMEN_FACTOR = 10


def generate_graphs(
    df_cell: DataFrame,
    df_label: DataFrame,
    validation_data_percent: int,
    test_data_percent: int,
    use_channels: bool = True,
    use_phenotypes: bool = True,
    roi_side_length: int | None = None,
    cells_per_roi_target: int | None = 10_000,
    exclude_unlabeled: bool = False,
    target_name: str | None = None,
    max_cells_to_consider: int = 100_000,
    n_neighbors: int = 5,
    threshold: int | None = None,
    random_seed: int | None = None,
    output_directory: str | None = None,
) -> tuple[list[GraphData], list[str]]:
    """Generate cell graphs from SMProfiler server extracts and save to disk if requested.

    Parameters
    ----------
    df_cell: DataFrame
        Rows are individual cells, indexed by an integer ID.
        Column or column groups are, named and in order:
            1. The 'specimen' the cell is from
            2. Cell centroid positions 'pixel x' and 'pixel y'
            3. Channel expressions starting with 'C ' and followed by a human-readable symbol
            4. Phenotype expressions starting with 'P ' followed by a symbol
    df_label: DataFrame
        Rows are specimens, the sole column 'label' is its class label as an integer.
    validation_data_percent: int
    test_data_percent: int
        Percent of regions of interest (ROIs) to reserve for the validation and test sets. Actual
        percentage of ROIs may not match because different specimens may yield different ROI counts,
        and the splitting process ensures that ROIs from the same specimen are not split among
        different train/validation/test sets.
        Set validation_data_percent to 0 if you want to do k-fold cross-validation later.
        (Training data percent is calculated from these two percentages.)
    use_channels: bool = True
    use_phenotypes: bool = True
        Whether to include channel or phenotype features (columns in df_cell beginning with 'C ' and
        'P ', respectively) in the graph.
    roi_side_length: int | None = None
    cells_per_roi_target: int | None = 10_000
        One of these must be provided in order to determine the ROI size. roi_side_length specifies
        how long to make the side length of each square ROI, in pixels. If this isn't provided, the
        median cell density across all slides is used with cells_per_roi_target to determine the
        square ROI sizing.
    exclude_unlabeled: bool = False
        If True, exclude specimens without labels from the training set.
    target_name: str | None = None
        If provided, decide ROI placement based on only cells with this channel or phenotype. (All
        cells will be included in the ROI, but the density of cells with this channel or phenotype
        will decide where each cell is placed.) Should be a column name in df_feat_all_specimens.
        If not provided, simply orient ROIs where all cells are densest.
    max_cells_to_consider: int = 100_000
        The maximum number of cells to consider when placing ROI bounds. All cells within each
        boundary region will be included in the graph, but the ROI's center will be based on the
        cell with the most and closest cells within the specified ROI size.
        Empirically 350,000 works but 400,000 gives a 1.75 TB square and an out of memory error.
    n_neighbors: int = 5
        Number of nearest neighbors to use when constructing the graph.
    threshold: int | None = None
        Maximum allowed distance between 2 nodes. Defaults to None (no thresholding).
    random_seed: int | None = None
        If provided, set the random seed to make the train/test/validation split deterministic.
    output_directory: str | None = None
        If provided, save the graphs to disk in the specified directory.

    Returns
    -------
    graphs_data: list[GraphData]
    feature_names: list[str]
        The names of the features in graph.ndata['features'] in the order they appear in the array.
    """
    if output_directory is not None:
        if exists(join(output_directory, 'graphs.bin')) and \
                exists(join(output_directory, 'feature_names.txt')):
            warn('Graphs already exist in output directory. Loading from file.')
            return load_hs_graphs(output_directory)
        else:
            makedirs(output_directory, exist_ok=True)
    p_validation, p_test, roi_size, roi_area, features_to_use, grouped = \
        prepare_graph_generation_by_specimen(
            df_cell,
            df_label,
            validation_data_percent,
            test_data_percent,
            use_channels=use_channels,
            use_phenotypes=use_phenotypes,
            roi_side_length=roi_side_length,
            cells_per_roi_target=cells_per_roi_target,
            random_seed=random_seed,
        )
    graphs_by_specimen: dict[str, list[HSGraph]] = {}
    print('Creating graphs for identified regions in each specimen...')
    for specimen, df_specimen in tqdm(grouped):
        # Skip specimens without labels
        if exclude_unlabeled and (specimen not in df_label.index):
            continue
        graphs = create_graphs_from_specimen(
            df_specimen,
            features_to_use,
            roi_size,
            roi_area,
            target_name=target_name,
            max_cells_to_consider=max_cells_to_consider,
            n_neighbors=n_neighbors,
            threshold=threshold,
            random_seed=random_seed,
        )
        graphs_by_specimen[specimen] = graphs
        print(f'Created {len(graphs)} ROI(s) from specimen {specimen}.')
    graphs_data = finalize_graph_metadata(
        graphs_by_specimen,
        df_label,
        p_validation,
        p_test,
        roi_size,
        random_seed=random_seed,
    )
    if output_directory is not None:
        save_graph_data_and_feature_names(graphs_data, features_to_use, output_directory)
    return graphs_data, features_to_use


def prepare_graph_generation_by_specimen(
    df_cell: DataFrame,
    df_label: DataFrame,
    validation_data_percent: int,
    test_data_percent: int,
    use_channels: bool = True,
    use_phenotypes: bool = True,
    roi_side_length: int | None = None,
    cells_per_roi_target: int | None = 5_000,
    random_seed: int | None = None,
) -> tuple[
    float,
    float,
    tuple[int, int],
    float,
    list[str],
    DataFrameGroupBy,
]:
    """Prepare for graph generation by splitting the data by specimen and determining ROI size."""
    p_validation, p_test, roi_size = _validate_inputs(
        df_label,
        validation_data_percent,
        test_data_percent,
        use_channels,
        use_phenotypes,
        roi_side_length,
    )

    if random_seed is not None:
        set_seeds(random_seed)

    grouped, roi_size, roi_area, features_to_use = _group_by_specimen(
        df_cell,
        cells_per_roi_target,
        roi_size,
        use_channels,
        use_phenotypes,
    )
    return p_validation, p_test, roi_size, roi_area, features_to_use, grouped


def _validate_inputs(
    df_label: DataFrame,
    validation_data_percent: int,
    test_data_percent: int,
    use_channels: bool = True,
    use_phenotypes: bool = True,
    roi_side_length: int | None = None,
) -> tuple[float, float, tuple[int, int] | None]:
    """Validate graph generation inputs."""
    if not 0 <= validation_data_percent < 100:
        raise ValueError(
            f"Validation set percentage must be between 0 and 100, not {validation_data_percent}%."
        )
    if not 0 <= test_data_percent < 100:
        raise ValueError(
            f"Test set percentage must be between 0 and 100, not {test_data_percent}%."
        )
    train_data_percent = validation_data_percent + test_data_percent
    if not 0 <= train_data_percent < 100:
        raise ValueError(
            "Remaining data set percentage for training use must be between 0 and 100, not "
            f"{train_data_percent}%."
        )
    p_validation: float = validation_data_percent/100
    p_test: float = test_data_percent/100
    roi_size = None if roi_side_length is None else (roi_side_length, roi_side_length)
    if df_label['label'].nunique() < 2:
        raise ValueError('Less than two unique labels. No point to training.')
    if (not use_channels) and (not use_phenotypes):
        raise ValueError('Must use at least one of channels or phenotypes.')
    return p_validation, p_test, roi_size


def _group_by_specimen(
    df_cell: DataFrame,
    cells_per_roi_target: int | None = 5_000,
    roi_size: tuple[int, int] | None = None,
    use_channels: bool = True,
    use_phenotypes: bool = True,
) -> tuple[DataFrameGroupBy, tuple[int, int], float, list[str]]:
    df_cell, features_to_use = _prepare_df_cell(df_cell, use_channels, use_phenotypes)
    grouped, roi_size, roi_area = _split_df_by_specimen(
        df_cell,
        cells_per_roi_target,
        roi_size,
    )
    return grouped, roi_size, roi_area, features_to_use


def _prepare_df_cell(
    df_cell: DataFrame,
    use_channels: bool = True,
    use_phenotypes: bool = True,
) -> tuple[DataFrame, list[str]]:
    features_to_use: list[str] = []
    channels = df_cell.columns[df_cell.columns.str.startswith('C ')]
    phenotypes = df_cell.columns[df_cell.columns.str.startswith('P ')]
    if use_channels:
        features_to_use.extend(channels)
    else:
        df_cell.drop(columns=channels, inplace=True)
    if use_phenotypes:
        features_to_use.extend(phenotypes)
    else:
        df_cell.drop(columns=phenotypes, inplace=True)
    if len(features_to_use) == 0:
        raise ValueError('No features to use.')
    return df_cell, features_to_use


def _split_df_by_specimen(
    df_cell: DataFrame,
    cells_per_roi_target: int | None = 5_000,
    roi_size: tuple[int, int] | None = None,
) -> tuple[
    DataFrameGroupBy,
    tuple[int, int],
    float,
]:
    """Split data by specimen and derive the roi_size from the average cell density if needed."""
    grouped = df_cell.groupby('specimen')
    if roi_size is not None:
        roi_area = prod(roi_size)
    elif cells_per_roi_target is not None:
        roi_area: float = cells_per_roi_target / median([
            (df_specimen.shape[0] / prod(
                df_specimen[['pixel x', 'pixel y']].max() -
                df_specimen[['pixel x', 'pixel y']].min()
            )) for _, df_specimen in grouped
        ])
        roi_size = (rint(roi_area**0.5), rint(roi_area**0.5))
    else:
        raise ValueError('Must specify either roi_size or cells_per_roi_target.')
    return grouped, roi_size, roi_area


def create_graphs_from_specimen(
    df: DataFrame,
    features_to_use: list[str],
    roi_size: tuple[int, int],
    roi_area: float,
    target_name: str | None = None,
    max_cells_to_consider: int = 100_000,
    n_neighbors: int = 5,
    threshold: int | None = None,
    random_seed: int | None = None,
) -> list[HSGraph]:
    """Create graphs from a single specimen."""
    if random_seed is not None:
        set_seeds(random_seed)

    proportion_of_target, df_target = _assemble_target_df(df, target_name, max_cells_to_consider)
    bounding_boxes = _create_roi_bounding_boxes(
        df,
        roi_area,
        proportion_of_target,
        df_target,
        roi_size,
        n_neighbors,
    )
    return _create_graphs(df, features_to_use, bounding_boxes, n_neighbors, threshold)


def _assemble_target_df(
    df: DataFrame,
    target_name: str | None,
    max_cells_to_consider: int,
) -> tuple[float, DataFrame]:
    if target_name is not None:
        proportion_of_target = df[target_name].sum()/df.shape[0]
        df_target = df.loc[df[target_name], :]
    else:
        proportion_of_target = 1.
        df_target = df
    if df_target.shape[0] > max_cells_to_consider:
        df_target = df_target.sample(max_cells_to_consider)
    return proportion_of_target, df_target


def _create_roi_bounding_boxes(
    df: DataFrame,
    roi_area: float,
    proportion_of_target: float,
    df_target: DataFrame,
    roi_size: tuple[int, int],
    n_neighbors: int,
) -> list[tuple[int, int, int, int]]:
    """Create ROIs based on the proportion of cells on the source have the target phenotype.

    The total area of the ROIs will approximately equal the area of the source image times the
    proportion of cells on that image that have the target phenotype.
    """
    bounding_boxes: list[tuple[int, int, int, int]] = []
    slide_area = prod(df[['pixel x', 'pixel y']].max() - df[['pixel x', 'pixel y']].min())
    rois_in_slide = proportion_of_target * slide_area / roi_area
    n_rois: int = rint(rois_in_slide)
    if (n_rois == 0) and (rois_in_slide > MIN_THRESHOLD_TO_CREATE_ROI):
        n_rois = 1
    while (len(bounding_boxes) < n_rois) and (df_target.shape[0] > 0):
        x, y = _find_cell_with_most_targets_nearby(df_target, roi_size)
        x_min, x_max, y_min, y_max = _bounding_box_around(x, y, roi_size)
        if _not_enough_cells(df, x_min, x_max, y_min, y_max, n_neighbors):
            break
        bounding_boxes.append((x_min, x_max, y_min, y_max))
        df_target = _remove_cells_in_bounding_box(df_target, x_min, x_max, y_min, y_max)
    return bounding_boxes


def _find_cell_with_most_targets_nearby(
    df_target: DataFrame,
    roi_size: tuple[int, int],
) -> tuple[int, int]:
    tree = KDTree(df_target[['pixel x', 'pixel y']].values)
    counts = tree.query_radius(
        df_target[['pixel x', 'pixel y']].values,
        r=roi_size[0]//2,
        count_only=True,
    )
    x, y = df_target.iloc[argmax(counts), :][['pixel x', 'pixel y']].values
    return x, y


def _bounding_box_around(x: int, y: int, roi_size: tuple[int, int]) -> tuple[int, int, int, int]:
    x_min = x - roi_size[0]//2
    x_max = x + roi_size[0]//2
    y_min = y - roi_size[1]//2
    y_max = y + roi_size[1]//2
    return x_min, x_max, y_min, y_max


def _not_enough_cells(
    df: DataFrame,
    x_min: int,
    x_max: int,
    y_min: int,
    y_max: int,
    n_neighbors: int,
) -> bool:
    """Check if the bounding box contains enough cells to perform nearest neighbors on."""
    return (df['pixel x'].between(x_min, x_max) & df['pixel y'].between(y_min, y_max)).sum() < \
        n_neighbors + 1


def _remove_cells_in_bounding_box(
    df_target: DataFrame,
    x_min: int,
    x_max: int,
    y_min: int,
    y_max: int,
) -> DataFrame:
    """Remove the cells in the bounding box from the eligible target DataFrame."""
    return df_target.loc[~(
        df_target['pixel x'].between(x_min, x_max) & df_target['pixel y'].between(y_min, y_max)
    ), :]


def _create_graphs(
    df: DataFrame,
    features_to_use: list[str],
    bounding_boxes: list[tuple[int, int, int, int]],
    n_neighbors: int,
    threshold: int | None,
) -> list[HSGraph]:
    """Create features, centroid, and label arrays and then the graph."""
    graphs: list[HSGraph] = []
    for (x_min, x_max, y_min, y_max) in bounding_boxes:
        df_roi: DataFrame = df.loc[
            df['pixel x'].between(x_min, x_max) &
            df['pixel y'].between(y_min, y_max),
        ]
        graphs.append(_create_graph(
            df_roi.index.to_numpy(),
            df_roi[['pixel x', 'pixel y']].values,
            df_roi[features_to_use].astype(int).values,
            n_neighbors=n_neighbors,
            threshold=threshold,
        ))
    return graphs


def _create_graph(
    node_indices: NDArray[int_],
    centroids: NDArray[int_],
    features: NDArray[int_],
    n_neighbors: int = 5,
    threshold: int | None = None,
) -> HSGraph:
    """Generate the graph topology from the provided instance_map using (thresholded) kNN.

    Parameters
    ----------
    node_indices: NDArray[int_]
        Indices for each node.
    centroids: NDArray[int_]
        Node centroids
    features: NDArray[int_]
        Features of each node based on chemical channels.
    n_neighbors: int
        Number of neighbors. Defaults to 5.
    threshold: int | None
        Maximum allowed distance between 2 nodes. Defaults to None (no thresholding).

    Returns
    -------
    HSGraph: The constructed graph
    """
    adj = kneighbors_graph(
        centroids,
        n_neighbors,
        mode="distance",
        include_self=False,
        metric="euclidean",
    )
    if threshold is None:
        threshold = float('inf')
    adj.data = (adj.data <= threshold).astype(bool)
    return HSGraph(
        adj,
        features.astype(float),
        centroids,
        node_indices,
    )


def finalize_graph_metadata(
    graphs_by_specimen: dict[str, list[HSGraph]],
    df_label: DataFrame,
    p_validation: float,
    p_test: float,
    roi_size: tuple[int, int],
    random_seed: int | None = None,
) -> list[GraphData]:
    """Split into train/validation/test sets and associate other metadata with the graphs.

    If there's a mix of whole slide images (WSIs) and tissue microarrays (TMAs), this method
    allocates WSIs first, identified by how many ROIs are created from each image.
    """
    if random_seed is not None:
        set_seeds(random_seed)
    graphs_by_label_and_specimen = _split_graphs_by_label_and_specimen(graphs_by_specimen, df_label)
    specimen_to_set = _split_rois(graphs_by_label_and_specimen, p_validation, p_test)
    graphs_data = _assemble_graph_data(
        graphs_by_label_and_specimen,
        specimen_to_set,
        roi_size,
    )
    print(report_dataset_statistics(graphs_data))
    return graphs_data


def _split_graphs_by_label_and_specimen(
    graphs_by_specimen: dict[str, list[HSGraph]],
    df_label: DataFrame,
) -> dict[int | None, dict[str, list[HSGraph]]]:
    graphs_by_label_and_specimen: dict[int | None, dict[str, list[HSGraph]]] = DefaultDict(dict)
    for specimen, graphs in graphs_by_specimen.items():
        label: int | None = df_label.loc[specimen, 'label'] if (specimen in df_label.index) \
            else None
        graphs_by_label_and_specimen[label][specimen] = graphs
    return graphs_by_label_and_specimen


def _split_rois(
    graphs_by_label_and_specimen: dict[int | None, dict[str, list[HSGraph]]],
    p_validation: float,
    p_test: float,
) -> dict[str, SETS_type | None]:
    """Randomly allocate graphs to train, validation, and test sets."""
    p_train = 1 - p_validation - p_test
    specimen_to_set: dict[str, SETS_type | None] = {}
    for label, graphs_by_specimen in graphs_by_label_and_specimen.items():
        if label is None:
            for specimen in graphs_by_specimen:
                specimen_to_set[specimen] = None
            continue
        n_graphs = sum(len(l) for l in graphs_by_specimen.values())
        if n_graphs == 0:
            warn(f'Class {label} doesn\'t have any examples.')
            continue

        specimens = _shuffle_specimens(graphs_by_specimen)
        specimen = specimens[0]
        specimen_to_set[specimen] = SETS[0]
        n_specimens = len(specimens)
        if n_specimens == 1:
            warn(f'Class {label} only has one specimen. Allocating to training set.')
        elif n_specimens == 2:
            specimen_to_set[specimens[1]] = _set_for_second_of_2_specimens(
                p_validation, p_test, label)
        else:
            specimen_to_set, n_allocated_val, n_allocated_test, i_specimen = \
                _allocate_second_of_many(
                    graphs_by_specimen,
                    specimen_to_set,
                    specimens,
                    p_validation,
                    p_test,
                )
            n_train_target, n_validation_target = _calculate_set_targets(
                n_graphs,
                p_train,
                p_validation,
                p_test,
                len(graphs_by_specimen[specimens[0]]),
                n_allocated_val,
                n_allocated_test,
                label,
            )
            specimen_to_set = _allocate_remaining_specimens(
                specimen_to_set,
                graphs_by_specimen,
                specimens[i_specimen:],
                n_train_target,
                n_validation_target,
            )

    return specimen_to_set


def _shuffle_specimens(graphs_by_specimen: dict[str, list[HSGraph]]) -> list[str]:
    """Shuffle the specimen order, giving priority to "big" specimens."""
    specimens_with_counts = [
        (specimen, len(graphs)) for specimen, graphs in graphs_by_specimen.items()
    ]
    shuffle(specimens_with_counts)
    median_count = median([count for _, count in specimens_with_counts])
    big_threshold = BIG_SPECIMEN_FACTOR * median_count
    specimens_with_many_graphs: list[str] = []
    rest_of_specimens: list[str] = []
    for specimen, count in specimens_with_counts:
        if count >= big_threshold:
            warn(f'Large specimen detected. {specimen} has {count/median_count:.2g}x more ROIs '
                 f'({count}) than the median specimen ({median_count}). Prioritizing its '
                 'allocation.')
            specimens_with_many_graphs.append(specimen)
        else:
            rest_of_specimens.append(specimen)
    specimens = specimens_with_many_graphs + rest_of_specimens
    return specimens


def _set_for_second_of_2_specimens(
    p_validation: float,
    p_test: float,
    label: int,
) -> SETS_type:
    """Decide which of train, validation, or test to allocate the second of two specimens to."""
    if (p_validation == 0) and (p_test == 0):
        return SETS[0]
    elif p_test == 0:
        return SETS[1]
    elif p_validation == 0:
        return SETS[2]
    else:
        warn(f'Class {label} only has two specimens. '
             'Allocating one for training and the other randomly to validation or test.')
        if randint(0, 1) == 0:
            return SETS[1]
        else:
            return SETS[2]


def _allocate_second_of_many(
    graphs_by_specimen: dict[str, list[HSGraph]],
    specimen_to_set: dict[str, SETS_type | None],
    specimens: list[str],
    p_validation: float,
    p_test: float,
) -> tuple[dict[str, SETS_type | None], int, int, int]:
    """Allocate at least one specimen to each of the validation and test sets if necessary."""
    i_specimen: int = 1
    specimen = specimens[i_specimen]
    n_allocated_val = 0
    n_allocated_test = 0
    if p_validation > 0:
        specimen_to_set[specimen] = SETS[1]
        n_allocated_val = len(graphs_by_specimen[specimen])
        i_specimen += 1
        specimen = specimens[i_specimen]
    if p_test > 0:
        specimen_to_set[specimen] = SETS[2]
        n_allocated_test = len(graphs_by_specimen[specimen])
        i_specimen += 1
    return specimen_to_set, n_allocated_val, n_allocated_test, i_specimen


def _calculate_set_targets(
    n_graphs: int,
    p_train: float,
    p_validation: float,
    p_test: float,
    n_allocated_train: int,
    n_allocated_val: int,
    n_allocated_test: int,
    label: int,
) -> tuple[float, float]:
    """Calculate the number of ROIs still to allocate to train, validation, and test sets."""
    n_train_target = n_graphs * p_train - n_allocated_train
    n_validation_target = n_graphs * p_validation - n_allocated_val
    n_test_target = n_graphs * p_test - n_allocated_test
    if (n_train_target < 0) or (n_validation_target < 0) or (n_test_target < 0):
        which_sets: list[str] = []
        if n_train_target < 0:
            which_sets.append('train')
        if n_validation_target < 0:
            which_sets.append('validation')
        if n_test_target < 0:
            which_sets.append('test')
        warn(
            f'Class {label} doesn\'t have enough specimens to maintain the specified '
            f'{"/".join(which_sets)} proportion. Consider adding more specimens of this '
            'class and/or increasing their allocation percentage.'
        )
    return n_train_target, n_validation_target


def _allocate_remaining_specimens(
    specimen_to_set: dict[str, SETS_type | None],
    graphs_by_specimen: dict[str, list[HSGraph]],
    specimens: list[str],
    n_train_target: float,
    n_validation_target: float,
) -> dict[str, SETS_type | None]:
    """Allocate the remaining specimens to the train, validation, and test sets.

    Prioritizes bolstering the training and validation sets in that order.
    """
    n_used_of_remainder = 0
    n_train_and_validation_target = n_train_target + n_validation_target
    for specimen in specimens:
        specimen_files = graphs_by_specimen[specimen]
        if n_used_of_remainder < n_train_target:
            specimen_to_set[specimen] = SETS[0]
        elif n_used_of_remainder < n_train_and_validation_target:
            specimen_to_set[specimen] = SETS[1]
        else:
            specimen_to_set[specimen] = SETS[2]
        n_used_of_remainder += len(specimen_files)
    return specimen_to_set


def _assemble_graph_data(
    graphs_by_label_and_specimen: dict[int | None, dict[str, list[HSGraph]]],
    specimen_to_set: dict[str, SETS_type | None],
    roi_size: tuple[int, int],
) -> list[GraphData]:
    graph_data: list[GraphData] = []
    for label, graphs_by_specimen in graphs_by_label_and_specimen.items():
        for specimen, graph_list in graphs_by_specimen.items():
            for i, graph_instance in enumerate(graph_list):
                graph_data.append(GraphData(
                    graph_instance,
                    label,
                    f'{specimen}_{roi_size[0]}x{roi_size[1]}_{i}',
                    specimen,
                    specimen_to_set[specimen],
                ))
    return graph_data


def report_dataset_statistics(graphs_data: list[GraphData]) -> DataFrame:
    """Report the number of graphs created per class and set."""
    df = DataFrame(columns=['label', 'set', 'count'])
    for graph_instance in graphs_data:
        if graph_instance.specimen in df.index:
            df.loc[graph_instance.specimen, 'count'] += 1
        else:
            df.loc[graph_instance.specimen, :] = [graph_instance.label, graph_instance.set, 1]
    return df.groupby(['set', 'label']).sum()
