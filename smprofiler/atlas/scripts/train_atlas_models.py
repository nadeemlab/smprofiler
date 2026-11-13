"""
Command line entry point for atlas-reference model training.

Example:
    smprofiler atlas train-atlas-models \\
        --database-config-file database_config_file \\
        --output-dir models \\
        [--max-cells 500000] [--study luad_progression] [--dry-run]
"""
import argparse
import sys
from pathlib import Path

from smprofiler.standalone_utilities.module_load_error import SuggestExtrasException
from smprofiler.db.exchange_data_formats.atlas_models import CellAtlasSource
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('train-atlas-models')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='smprofiler atlas train-atlas-models',
        description="Train atlas-reference regression models for SMProfiler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--database-config-file",
        help="Database credentials file, see template in the repository."
    )
    parser.add_argument(
        "--atlas-source",
        default=CellAtlasSource.ALLEN_IMMUNE_HEALTH,
        help="Name of the source atlas",
    )
    parser.add_argument(
        "--output-dir",
        default="models",
        help="Output directory for ONNX models and metadata",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=None,
        help="Max number of atlas cells to use (random sample). None = use all",
    )
    parser.add_argument(
        "--study",
        default=None,
        help="Train only for this study (default: all discovered studies)",
    )
    parser.add_argument(
        "--cv-folds",
        type=int,
        default=5,
        help="Number of cross-validation folds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the training plan without actually training any models",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


def main(args: argparse.Namespace) -> None:
    try:
        from smprofiler.atlas import training
        from smprofiler.atlas.reporting import set_atlas_log_level
        from smprofiler.atlas.reporting import suppress_third_party_logging
    except ModuleNotFoundError as exception:
        SuggestExtrasException(exception, 'atlas')
        raise exception

    suppress_third_party_logging()
    set_atlas_log_level(args.verbose)

    try:
        training.run(
            Path(args.database_config_file),
            Path(args.output_dir),
            max_cells=args.max_cells,
            study=args.study,
            cv_folds=args.cv_folds,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError) as exception:
        logger.error('%s', exception)
        sys.exit(1)


if __name__ == "__main__":
    main(parse_args())

