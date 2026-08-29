"""Access to the aggregated atlas artifacts.

Reads the two files produced by the atlas aggregation step (in smprofiler-data):

- ``cell_atlas_small.parquet`` — a cell × gene expression table restricted to
  the atlas genes relevant to SPT channels.
- ``smprofiler_channels_to_atlas.tsv`` — the manual mapping from SPT channel
  names to atlas gene (column) names.

The aggregation step subselects and joins the per-cell-type atlas downloads and
applies the manually curated ``channel_proxies.json``; this module simply
consumes its Parquet/TSV output. (The heuristic fallback mapping lives in
:mod:`smprofiler.atlas.automatic_channel_mapping`.)
"""
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.reporting import format_elapsed

logger = colorized_logger(__name__)

# Column headers in smprofiler_channels_to_atlas.tsv
_SPT_COLUMN = "SMProfiler channel name"
_ATLAS_COLUMN = "Atlas gene name"


def load_channel_mapping(mapping_path: Path) -> dict[str, str]:
    """
    Load the manual SPT-channel → atlas-gene mapping from the aggregation TSV.

    The TSV has columns ``"SMProfiler channel name"`` and ``"Atlas gene name"``.
    Several SPT channels may map to the same atlas gene (e.g. CD45, CD45RA and
    CD45RO all map to PTPRC), so the returned dict is many-to-one.

    Returns:
        dict mapping spt_channel_name → atlas_gene_name.
    """
    df = pd.read_csv(mapping_path, sep="\t")
    missing = {_SPT_COLUMN, _ATLAS_COLUMN} - set(df.columns)
    if missing:
        raise ValueError(
            f"Channel mapping {mapping_path} is missing column(s) {sorted(missing)}; "
            f"found {list(df.columns)}"
        )
    spt_to_atlas = {
        str(spt).strip(): str(atlas).strip()
        for spt, atlas in zip(df[_SPT_COLUMN], df[_ATLAS_COLUMN])
        if pd.notna(spt) and pd.notna(atlas)
    }
    logger.info(
        "Channel mapping: %d SPT channels → %d atlas genes (from %s)",
        len(spt_to_atlas), len(set(spt_to_atlas.values())), mapping_path,
    )
    return spt_to_atlas


def load_atlas_gene_names(parquet_path: Path) -> list[str]:
    """Return the gene (column) names of the atlas Parquet table, without loading data."""
    size_mb = parquet_path.stat().st_size / 1024 ** 2
    schema = pq.read_schema(parquet_path)
    names = list(schema.names)
    n_rows = pq.ParquetFile(parquet_path).metadata.num_rows
    logger.info(
        "Atlas parquet (%.1f MB): %s cells × %d genes — %s",
        size_mb, f"{n_rows:,}", len(names), parquet_path,
    )
    return names


def load_atlas_subset(
    parquet_path: Path,
    atlas_columns: list[str],
    spt_names: list[str],
    max_cells: int | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, list[str]]:
    """
    Load specific gene columns from the atlas Parquet table into memory.

    Args:
        parquet_path: path to cell_atlas_small.parquet
        atlas_columns: atlas gene names to load (may contain duplicates when
            several SPT channels share one atlas gene; each entry becomes its
            own output column)
        spt_names: corresponding SPT channel names (same length as atlas_columns)
        max_cells: if set, randomly sample this many cells
        rng: random number generator for sampling

    Returns:
        (X, spt_names) where X has shape (n_cells, len(atlas_columns)).
    """
    logger.info("Loading %d atlas columns from parquet: %s", len(atlas_columns), atlas_columns)
    t0 = time.monotonic()

    # Read each distinct gene column once; duplicate SPT→gene entries are
    # expanded back out when assembling X below.
    unique_columns = list(dict.fromkeys(atlas_columns))
    parquet_file = pq.ParquetFile(parquet_path)
    n_total = parquet_file.metadata.num_rows
    table = parquet_file.read(columns=unique_columns)

    if max_cells and n_total > max_cells:
        if rng is None:
            rng = np.random.default_rng(42)
        idx = np.sort(rng.choice(n_total, size=max_cells, replace=False))
        table = table.take(idx)
        logger.info(
            "Sampling %s / %s cells from atlas (%.1f%%)…",
            f"{max_cells:,}", f"{n_total:,}", 100 * max_cells / n_total,
        )
    else:
        logger.info("Loading all %s cells from atlas…", f"{n_total:,}")

    column_values = {
        name: table.column(name).to_numpy(zero_copy_only=False).astype(np.float32)
        for name in unique_columns
    }
    X = np.column_stack([column_values[name] for name in atlas_columns]).astype(np.float32)

    logger.info(
        "Atlas data loaded in %s — shape %s (%.1f MB)",
        format_elapsed(time.monotonic() - t0),
        X.shape,
        X.nbytes / 1024 ** 2,
    )
    return X, spt_names
