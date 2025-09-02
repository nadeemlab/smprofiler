"""GNN importance fractions figure generation

This is generated programmatically from extractions from Graph Neural Network models.
"""

from argparse import ArgumentParser

import matplotlib.pyplot as plt

from smprofiler.graphs.config_reader import read_plot_importance_fractions_config
from smprofiler.graphs.importance_fractions import PlotGenerator


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs plot-importance-fractions',
        description="""Generate GNN-derived importance score fractions plot."""
    )
    parser.add_argument(
        '--config_path',
        type=str,
        help='Path to the configuration TOML file.',
        required=True,
    )
    parser.add_argument(
        '--output_filename',
        type=str,
        default=None,
        help='Filename to save the plot to. (Plot file type is chosen based on the extension.)',
    )
    parser.add_argument(
        '--show',
        action='store_true',
        help='If set, will display figures in addition to saving.',
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    if not args.show and (args.output_filename is None):
        raise ValueError('Nothing requested of the plot, skipping.')
    (
        host_name,
        study_name,
        phenotypes,
        cohorts,
        plugins,
        figure_size,
        orientation,
    ) = read_plot_importance_fractions_config(args.config_path)
    generator = PlotGenerator(
        host_name,
        study_name,
        phenotypes,
        cohorts,
        plugins,
        figure_size,
        orientation,
    )
    fig = generator.generate_plot()
    if args.output_filename is not None:
        plt.savefig(args.output_filename)
    if args.show:
        plt.show()
