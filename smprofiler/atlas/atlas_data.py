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
from smprofiler.atlas.channel_annotations import normalize_name

logger = colorized_logger(__name__)


def load_channel_mapping(mapping_path: Path) -> dict[str, str]:
    """
    Load the manual SMProfiler-channel → atlas-gene mapping.

    The source TSV has columns ``SMProfiler channel name`` and ``Atlas gene name``.
    Several SMProfiler channels may map to the same atlas gene (e.g. CD45, CD45RA and
    CD45RO all map to PTPRC), so the returned dict is many-to-one.

    Returns:
        dict mapping smprofiler_channel_name → atlas_gene_name.
    """
    df = pd.read_csv(mapping_path, sep="\t")
    columns = ('SMProfiler channel name', 'Atlas gene name')
    if tuple(df.columns) != columns:
        raise ValueError(f'Wrong columns: {columns}')
    return dict(df.itertuples(index=False))

def report_parquet_attributes(path: Path, smprofiler_to_atlas: dict[str, str]) -> None:
    size_mb = path.stat().st_size / 1024 ** 2
    schema = pq.read_schema(path)
    names = list(schema.names)
    n_rows = pq.ParquetFile(path).metadata.num_rows
    logger.info(
        "Atlas parquet (%.1f MB): %s cells × %d genes — %s",
        size_mb, f"{n_rows:,}", len(names), path,
    )
    missing = set(smprofiler_to_atlas.values()).difference(names)
    if len(missing) > 0:
        logger.error('Atlas does not actually contain: %s', missing)
    else:
        logger.info('All manually-mapped-to atlas gene names are actually in atlas.')
 
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
