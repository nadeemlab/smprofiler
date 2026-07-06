#!/usr/bin/env python3
"""Command line entry point for atlas-reference model training.

For each (study, functional_marker) pair, trains a regression model on the
Allen Institute Human Immune Health Atlas that predicts functional marker
intensity from identity marker values, and exports it to ONNX. See
``smprofiler.atlas`` for the library implementation.

Example:
    smprofiler atlas train-atlas-models \\
        --atlas /path/to/human_immune_health_atlas_full.h5ad \\
        --annotations /path/to/annotations/channel_annotations.json \\
        --datasets-dir /path/to/datasets \\
        --output-dir models \\
        [--max-cells 500000] [--study luad_progression] [--dry-run]
"""
import argparse
import os
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
        description="Train atlas-reference regression models for SPT",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--atlas",
        default=str(data_dir / "human_immune_health_atlas_full.h5ad"),
        help="Path to the Allen Institute Human Immune Health Atlas h5ad file",
    )
    parser.add_argument(
        "--annotations",
        default=str(data_dir / "annotations" / "channel_annotations.json"),
        help="Path to channel_annotations.json",
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
        "--atlas-mapping",
        default=None,
        help="Optional JSON file with extra atlas_var_name → spt_channel_name mappings",
    )
    parser.add_argument(
        "--annotations-api-url",
        default=DEFAULT_ANNOTATIONS_API_URL,
        help=(
            "Base URL for the smprofiler API used to fetch channel annotations. "
            "Used as the primary source; falls back to --annotations local file on failure. "
            "Pass an empty string to skip the API and use only the local file."
        ),
    )
    parser.add_argument(
        "--hgnc-cache",
        default=str(data_dir / "hgnc_symbol_cache.json"),
        help=(
            "Path to the HGNC symbol normalization cache (JSON). "
            "Created on first run via mygene.info + HGNC REST API; "
            "subsequent runs use only the cached data (fully offline). "
            "Pass an empty string to disable HGNC normalization entirely."
        ),
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

    suppress_third_party_logging()
    set_atlas_log_level(args.verbose)

    try:
        training.run(
            Path(args.atlas),
            Path(args.annotations),
            Path(args.datasets_dir),
            Path(args.output_dir),
            atlas_mapping=Path(args.atlas_mapping) if args.atlas_mapping else None,
            annotations_api_url=args.annotations_api_url,
            hgnc_cache=Path(args.hgnc_cache) if args.hgnc_cache else None,
            max_cells=args.max_cells,
            study=args.study,
            cv_folds=args.cv_folds,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, RuntimeError) as exception:
        logger.error("%s", exception)
        raise SystemExit(1) from exception


if __name__ == "__main__":
    main(parse_args())
