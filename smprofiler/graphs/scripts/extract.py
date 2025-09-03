"""Extract graph data artifacts as DataFrames and save to file."""

from argparse import ArgumentParser
from os import makedirs
from os.path import join
from os.path import exists
from json import dump

from smprofiler.graphs.config_reader import read_extract_config
from smprofiler.graphs.extract import extract


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs extract',
        description="""Extract information needed to create graphs from a single-cell dataset.

This command is intended to be used after you have identified which strata you want to use with `smprofiler
graphs explore-classes`.

```bash
smprofiler graphs extract --config_path path/to/extract.config --output_directory path/to/output/directory
```

This extracts single-cell data and strata/class information to three files in the output directory:
    * `cells.h5`, a binary HDF5 file containing cell information at the individual cell level, such
      as its xy position, channel, and phenotype expressions, as a pandas DataFrame.
    * `labels.h5`, a binary HDF file of a pandas DataFrame containing the class label of each tissue
      specimen as an integer ID, which is automatically derived from the strata information.
    * `label_to_result.json` is a simple JSON that translates each label ID to a human-interpretable
      description, for use in visualizations after training.

These files can be used with the standalone `smprofiler graphs generate-graphs` to create cell graphs.
"""
    )
    parser.add_argument(
        '--config_path',
        type=str,
        help='Path to the graph generation configuration TOML file.',
        required=True
    )
    parser.add_argument(
        '--output_directory',
        type=str,
        help='Directory to save extracted data to.',
        required=True
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    config_values = read_extract_config(args.config_path)
    dict_filename = join(args.output_directory, 'label_to_result.json')
    cells_filename = join(args.output_directory, 'cells.h5')
    labels_filename = join(args.output_directory, 'labels.h5')
    if not (exists(dict_filename) and exists(cells_filename) and exists(labels_filename)):
        makedirs(args.output_directory, exist_ok=True)
        df_cell, df_label, label_to_result = extract(*config_values)
        df_cell.to_hdf(cells_filename, 'cells')
        df_label.to_hdf(labels_filename, 'labels')
        with open(dict_filename, 'w', encoding='utf-8') as f:
            dump(label_to_result, f)
