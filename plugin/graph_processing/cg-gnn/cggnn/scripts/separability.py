"""Explain a cell graph (CG) prediction using a pretrained CG-GNN and a graph explainer."""

from argparse import ArgumentParser

from cggnn.run import find_separability


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        description='Explain a cell graph prediction using a model and a graph explainer.',
    )
    parser.add_argument(
        '--cg_path',
        type=str,
        help='Directory with the cell graphs, metadata, and feature names.',
        required=True
    )
    parser.add_argument(
        '--feature_names_path',
        type=str,
        help='Path to the list of feature names.',
        required=True
    )
    parser.add_argument(
        '--model_checkpoint_path',
        type=str,
        help='Path to the model checkpoint.',
        required=True
    )
    parser.add_argument(
        '--label_to_result_path',
        type=str,
        help='Where to find the data mapping label ints to their string results.',
        required=False
    )
    parser.add_argument(
        '--prune_misclassified',
        help='Remove entries for misclassified cell graphs when calculating separability scores.',
        action='store_true'
    )
    parser.add_argument(
        '--output_directory',
        type=str,
        help='Where to save the output reporting.',
        default=None,
        required=False
    )
    parser.add_argument(
        '--random_seed',
        type=int,
        help='Random seed to use for reproducibility.',
        default=None,
        required=False
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    find_separability(args.cg_path,
                      args.model_checkpoint_path,
                      args.label_to_result_path,
                      args.prune_misclassified,
                      args.output_directory,
                      args.random_seed)
