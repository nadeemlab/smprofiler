#!/usr/bin/env python3
"""Command line entry point for atlas-reference model training.

Example:
    smprofiler atlas train-atlas-models \\
        --atlas-parquet /path/to/cell_atlas_small.parquet \\
        --channel-mapping /path/to/smprofiler_channels_to_atlas.tsv \\
        --datasets-dir /path/to/datasets \\
        --output-dir models \\
        [--max-cells 500000] [--study luad_progression] [--dry-run]
"""
import argparse
import os
import sys
from pathlib import Path

from smprofiler.standalone_utilities.module_load_error import SuggestExtrasException
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('train-atlas-models')

DEFAULT_ANNOTATIONS_API_URL = "https://smprofiler.io/api"


def _default_data_dir() -> Path:
    """Directory holding the atlas file, annotations, and per-study datasets.

    Defaults to a ``smprofiler-data`` directory beside the repository — the
    layout of a source checkout run from its root. Override with the
    ``SMPROFILER_DATA_DIR`` environment variable or the explicit path flags.
    """
    override = os.environ.get("SMPROFILER_DATA_DIR")
    if override:
        return Path(override)
    return Path.cwd().parent / "smprofiler-data"


def parse_args() -> argparse.Namespace:
    data_dir = _default_data_dir()

    parser = argparse.ArgumentParser(
        prog='smprofiler atlas train-atlas-models',
        description="Train atlas-reference regression models for SMProfiler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--atlas-parquet",
        default=str(data_dir / "cell_atlas_small.parquet"),
        help="Path to the aggregated atlas expression table (cell_atlas_small.parquet)",
    )
    parser.add_argument(
        "--channel-mapping",
        default=str(data_dir / "smprofiler_channels_to_atlas.tsv"),
        help="Path to the SMProfiler-channel → atlas-gene mapping (smprofiler_channels_to_atlas.tsv)",
    )
    parser.add_argument(
        "--datasets-dir",
        default=str(data_dir / "datasets"),
        help="Root directory containing per-study dataset folders",
    )
    parser.add_argument(
        "--output-dir",
        default="models",
        help="Output directory for ONNX models and metadata",
    )
    parser.add_argument(
        "--annotations-api-url",
        default=DEFAULT_ANNOTATIONS_API_URL,
        help="Base URL for the smprofiler API used to fetch channel annotations",
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
        "--database-config-file",
        default=None,
        help=(
            "Optional smprofiler database config file. If given, each trained model "
            "(ONNX + metadata) is also stored in the 'atlas_model' table; otherwise "
            "models are written as files only."
        ),
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
            Path(args.atlas_parquet),
            Path(args.channel_mapping),
            Path(args.datasets_dir),
            Path(args.output_dir),
            annotations_api_url=args.annotations_api_url,
            max_cells=args.max_cells,
            study=args.study,
            cv_folds=args.cv_folds,
            dry_run=args.dry_run,
            database_config_file=Path(args.database_config_file) if args.database_config_file else None,
        )
    except (FileNotFoundError, RuntimeError) as exception:
        logger.error('%s', exception)
        sys.exit(1)


if __name__ == "__main__":
    main(parse_args())

