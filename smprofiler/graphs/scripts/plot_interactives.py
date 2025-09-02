"""Plot interactive cell graph visualizations."""

from argparse import ArgumentParser

from smprofiler.graphs.interactives import plot_interactives
from smprofiler.graphs.util import load_hs_graphs


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs plot-interactives',
        description="Plot HTML interactives from classified cell graphs."
    )
    parser.add_argument(
        '--cg_path',
        type=str,
        help='Directory with the cell graphs, metadata, and feature names.',
        required=True
    )
    parser.add_argument(
        '--merge_rois',
        help='Merge ROIs together by specimen.',
        action='store_true'
    )
    parser.add_argument(
        '--output_directory',
        type=str,
        help='Where to save the output graph visualizations.',
        default=None,
        required=False
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    graphs_data, feature_names = load_hs_graphs(args.cg_path)
    plot_interactives(graphs_data, feature_names, args.output_directory, args.merge_rois)
