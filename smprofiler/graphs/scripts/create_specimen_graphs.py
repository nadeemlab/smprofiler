"""Creates graphs from a single specimen."""

from typing import cast
from argparse import ArgumentParser
from os import makedirs
from os.path import join, basename, splitext
from pickle import load, dump

from pandas import read_hdf
from pandas import DataFrame

from smprofiler.graphs.generate_graphs import create_graphs_from_specimen


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs create-specimen-graphs',
        description="""Generate graphs from a single specimen.

Intended to be used with prepare-graph-creation and finalize-graphs.
"""
    )
    parser.add_argument(
        '--specimen_hdf_path',
        type=str,
        help='Path to the specimen cell attributes HDF.',
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
            target_name,
            max_cells_to_consider,
            n_neighbors,
            threshold,
            roi_size,
            roi_area,
            features_to_use,
            _,
            _,
            _,
            random_seed,
        ) = load(f)
    graphs = create_graphs_from_specimen(
        cast(DataFrame, read_hdf(args.specimen_hdf_path)),
        features_to_use,
        roi_size,
        roi_area,
        target_name=target_name,
        max_cells_to_consider=max_cells_to_consider,
        n_neighbors=n_neighbors,
        threshold=threshold,
        random_seed=random_seed,
    )
    if len(graphs) > 0:
        makedirs(args.output_directory, exist_ok=True)
        with open(join(
            args.output_directory,
            f'{splitext(basename(args.specimen_hdf_path))[0]}.pkl',
        ), 'wb') as f:
            dump(graphs, f)
