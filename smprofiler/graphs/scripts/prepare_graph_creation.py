"""Prepare data extracts from DB for parallel graph creation."""

from argparse import ArgumentParser
from os import makedirs
from os.path import join
from pickle import dump

from tqdm import tqdm  # type: ignore

from smprofiler.graphs.config_reader import read_extract_config, read_generation_config
from smprofiler.graphs.extract import extract
from smprofiler.graphs.generate_graphs import prepare_graph_generation_by_specimen


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs prepare-graph-creation',
        description="""Create files necessary for parallelized graph creation.

Intended to be used with parallel calls to create-specimen-graphs, followed by finalize-graphs.
"""
    )
    parser.add_argument(
        '--config_path',
        type=str,
        help='Path to the data extraction and graph generation configuration TOML file.',
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
    extract_config = read_extract_config(args.config_path)
    generation_config = read_generation_config(args.config_path)
    prep_generation_config = generation_config[:6]
    exclude_unlabeled: bool = generation_config[6]
    specimen_generation_config = generation_config[7:11]
    random_seed: int | None = generation_config[11]

    df_cell, df_label, label_to_result = extract(*extract_config)
    specimens_directory = join(args.output_directory, 'specimens')
    makedirs(specimens_directory, exist_ok=True)
    p_validation, p_test, roi_size, roi_area, features_to_use, grouped = \
        prepare_graph_generation_by_specimen(
            df_cell,
            df_label,
            *prep_generation_config,
            random_seed=random_seed,
        )
    with open(join(args.output_directory, 'parameters.pkl'), 'wb') as f:
        dump((
            *specimen_generation_config,
            roi_size,
            roi_area,
            features_to_use,
            df_label,
            p_validation,
            p_test,
            random_seed,
        ), f)
    for specimen, df_specimen in tqdm(grouped):
        # Skip specimens without labels
        if exclude_unlabeled and (specimen not in df_label.index):
            continue
        df_specimen.to_hdf(join(specimens_directory, f'{specimen}.h5'), 'cells')
