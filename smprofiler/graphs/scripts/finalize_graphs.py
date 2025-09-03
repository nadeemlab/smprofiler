"""Finalize graphs created via parallel processing."""

from argparse import ArgumentParser
from os.path import basename, splitext
from pickle import load

from smprofiler.graphs.generate_graphs import finalize_graph_metadata
from smprofiler.graphs.util import HSGraph, save_graph_data_and_feature_names


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs finalize-graphs',
        description="""Finalize created graphs.

Splits graphs into train/validation/test sets. This command is intended to be used with
prepare-graph-creation and parallel create-specimen-graphs calls.
"""
    )
    parser.add_argument(
        '--graph_files',
        type=str,
        nargs='+',
        help='Paths to the graph files.',
        required=True
    )
    parser.add_argument(
        '--parameters_path',
        type=str,
        help='Path to the graph creation parameter pickle file.',
        required=True
    )
    parser.add_argument(
        '--output_directory',
        type=str,
        help='Save files to this directory.',
        required=True
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    with open(args.parameters_path, 'rb') as f:
        (
            _,
            _,
            _,
            _,
            roi_size,
            _,
            features_to_use,
            df_label,
            p_validation,
            p_test,
            random_seed,
        ) = load(f)
    graphs_by_specimen: dict[str, list[HSGraph]] = {}
    for specimen_graphs_path in args.graph_files:
        with open(specimen_graphs_path, 'rb') as f:
            graphs_by_specimen[splitext(basename(specimen_graphs_path))[0]] = load(f)
    graphs_data = finalize_graph_metadata(
        graphs_by_specimen,
        df_label,
        p_validation,
        p_test,
        roi_size,
        random_seed=random_seed,
    )
    save_graph_data_and_feature_names(graphs_data, features_to_use, args.output_directory)
