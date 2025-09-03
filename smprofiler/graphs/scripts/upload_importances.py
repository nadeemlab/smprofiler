"""Upload importance score output from a graph plugin instance to the local db."""

from argparse import ArgumentParser

from pandas import read_csv

from smprofiler.db.importance_score_transcriber import transcribe_importance
from smprofiler.graphs.config_reader import read_upload_config


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler graphs upload-importances',
        description='Save cell importance scores to the database.',
    )
    parser.add_argument(
        '--importances_csv_path',
        type=str,
        help='File location for the importances CSV.',
        required=True
    )
    parser.add_argument(
        '--config_path',
        type=str,
        help='Path to the graph generation configuration TOML file.',
        required=True
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    (
        db_config_file_path,
        study_name,
        plugin_used,
        datetime_of_run,
        plugin_version,
        cohort_stratifier,
    ) = read_upload_config(args.config_path)
    df = read_csv(args.importances_csv_path, index_col=0)
    transcribe_importance(
        df,
        db_config_file_path,
        study_name,
        plugin_used,
        datetime_of_run,
        plugin_version,
        cohort_stratifier,
    )
