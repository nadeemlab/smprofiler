"""Convenience CLI wrapper of FeatureMatrixExtractor functionality, writes to files."""

import argparse
from os.path import exists
from os.path import abspath
from os.path import expanduser

from smprofiler.standalone_utilities.module_load_error import \
    SuggestExtrasException
try:
    from smprofiler.db.feature_matrix_extractor import FeatureMatrixExtractor
except ModuleNotFoundError as e:
    SuggestExtrasException(e, 'db')
from smprofiler.db.feature_matrix_extractor import FeatureMatrixExtractor

from smprofiler.workflow.common.cli_arguments import add_argument


def retrieve(args: argparse.Namespace):
    database_config_file = None
    if args.database_config_file:
        database_config_file = abspath(expanduser(args.database_config_file))
        if not exists(database_config_file):
            message = f'Need to supply valid database config filename: {database_config_file}'
            raise FileNotFoundError(message)
    extractor = FeatureMatrixExtractor(database_config_file=database_config_file)
    feature_matrices = extractor.extract(args.study_name)
    for _, specimen_data in feature_matrices.items():
        specimen_data.dataframe.to_csv(specimen_data.filename, sep='\t', index=False)
    outcomes = extractor.extract_cohorts(args.study_name)['assignments']
    filename = 'assignments.tsv'
    outcomes.to_csv(filename, sep='\t', index=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler db retrieve-feature-matrices',
        description='''
Retrieve feature matrices for each sample of a study and corresponding outcomes
dataframe and column/channel names lookup from any database that conforms to
"single cell ADI" database schema and writes them as TSV files to the current
working directory, with filenames listed alongside specimen and channel name
information in: features.json
''',

    )
    add_argument(parser, 'database config')
    add_argument(parser, 'study name')
    retrieve(parser.parse_args())
