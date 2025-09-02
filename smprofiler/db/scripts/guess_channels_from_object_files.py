"""Utility to scan a bundle of CSV/TSV cell or structure files for possible channel names."""
import argparse
import csv
import re
import json

from smprofiler.standalone_utilities.module_load_error import SuggestExtrasException
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('guess-channels-from-object-files')


def parse_channels(columns):
    patterns = {
        'membership': r'^(\w[\w _\d]+)[ _]Positive([ _]Classification)?$',
        'intensity': r'^(\w[\w _\d]+)(?<![ _]Nucleus)(?<![ _]Cytoplasm)'
                     r'(?<![ _]Membrane)[ _](Cell[ _])?Intensity$',
    }
    available = {kind: [] for kind in patterns}
    for column in columns:
        for kind, pattern in patterns.items():
            match = re.match(pattern, column)
            if match:
                available[kind].append((match.group(1), column))
    return available


def intersect_available(parsed_columns_list):
    available = parsed_columns_list[0]
    for parsed in parsed_columns_list:
        for kind in ['membership', 'intensity']:
            available[kind] = sorted(
                list(set(available[kind]).intersection(parsed[kind])))
    return available


def create_elementary_phenotypes_table(available_channels):
    records = []
    for phenotype_string, _ in available_channels['membership']:
        records.append({
            'Name': phenotype_string,
            'Column header fragment prefix': phenotype_string,
        })
    return pd.DataFrame(records)[['Name', 'Column header fragment prefix']]


def main(args):
    cell_files = args.cell_files
    known_channels = []
    for cell_file in cell_files:
        with open(cell_file, 'rt', encoding='utf-8') as file:
            reader = csv.reader(file)
            header = next(reader)
        logger.info('Parsing from %s', cell_file)
        channels = parse_channels(header)
        logger.debug('Got:\n%s', json.dumps(channels, indent=4))
        known_channels.append(channels)
    available_channels = intersect_available(known_channels)
    logger.info('In common in all files:\n%s',
                json.dumps(available_channels, indent=4))
    if len(available_channels['intensity']) == 0:
        logger.warning(
            'No channel intensity columns in common in the given set of cell/object files.')
    if len(available_channels['membership']) == 0:
        message = 'No channel positivity columns in common in the given set of cell/object files.'
        logger.error(message)
        raise ValueError(message)
    elementary_phenotypes = create_elementary_phenotypes_table(
        available_channels)
    elementary_phenotypes.to_csv(args.output_file, index=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler db guess-channels-from-object-files',
        description='Attempt to extract channel information from a list of tabular cell manifest '
        'files.'
    )

    parser.add_argument(
        'cell_files',
        nargs='+',
    )
    parser.add_argument(
        '--output-file',
        dest='output_file',
        type=str,
        required=True,
    )

    parsed_args = parser.parse_args()

    try:
        import pandas as pd
    except ModuleNotFoundError as exception:
        SuggestExtrasException(exception, 'db')
    main(parsed_args)
