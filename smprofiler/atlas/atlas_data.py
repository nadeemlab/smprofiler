"""Atlas file access and atlas ↔ SPT channel mapping.

Reads the Allen Institute atlas h5ad file (index-only or a column/row subset)
and reconciles atlas marker names with canonical SPT channel names through a
tiered manual / alias / case-insensitive / HGNC-symbol resolution.
"""
import time
from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.channel_annotations import normalize_name
from smprofiler.atlas.hgnc_normalization import normalize_names_to_hgnc
from smprofiler.atlas.reporting import format_elapsed

logger = colorized_logger(__name__)


def load_atlas_var_names(atlas_path: Path) -> list[str]:
    """Return var_names from the atlas without loading the expression matrix."""
    size_gb = atlas_path.stat().st_size / 1024 ** 3
    logger.info("Opening atlas (%.1f GB): %s", size_gb, atlas_path)
    t0 = time.monotonic()
    adata = ad.read_h5ad(atlas_path, backed="r")
    var_names = list(adata.var_names)
    n_obs = adata.n_obs
    adata.file.close()
    logger.info(
        "Atlas index loaded in %s — %s cells × %d markers",
        format_elapsed(time.monotonic() - t0), f"{n_obs:,}", len(var_names),
    )
    return var_names


def build_atlas_channel_map(
    atlas_var_names: list[str],
    spt_channels: set,
    aliases: dict,
    extra_mapping: dict | None = None,
    hgnc_cache_path: Path | None = None,
) -> dict[str, str]:
    """
    Build a mapping: atlas_var_name → canonical SPT channel name.

    Resolution order:
    1. Extra manual mapping (channel_name_mapping.json)
    2. Alias lookup (e.g. atlas has 'CD8A', SPT has 'CD8' via alias CD8A→CD8)
    3. Exact case-insensitive match
    4. HGNC normalization: both atlas name and SPT name normalized to the HGNC
       approved symbol; match on that shared canonical form. Only fires if
       hgnc_cache_path is provided.

    Returns dict of {atlas_var_name: spt_canonical_name} for matched entries only.
    """
    extra = extra_mapping or {}

    # Build case-insensitive SPT lookup for tier 3
    spt_channels_upper = {c.upper(): c for c in spt_channels}

    # Tier 4: HGNC normalization pre-computation
    # hgnc_spt_map:     approved_hgnc_symbol → spt_canonical
    # hgnc_atlas_lookup: atlas_name → approved_hgnc_symbol
    hgnc_spt_map: dict[str, str] = {}
    hgnc_atlas_lookup: dict[str, str] = {}
    if hgnc_cache_path is not None:
        all_names_for_hgnc = list(atlas_var_names) + list(spt_channels)
        hgnc_norm = normalize_names_to_hgnc(all_names_for_hgnc, hgnc_cache_path)
        # Build reverse: HGNC symbol → SPT canonical (first mapping wins)
        for spt_ch in spt_channels:
            h = hgnc_norm.get(spt_ch, spt_ch)
            if h not in hgnc_spt_map:
                hgnc_spt_map[h] = spt_ch
        # Build atlas → HGNC lookup
        for atlas_name in atlas_var_names:
            hgnc_atlas_lookup[atlas_name] = hgnc_norm.get(atlas_name, atlas_name)

    atlas_to_spt: dict[str, str] = {}
    hgnc_match_count = 0
    for atlas_name in atlas_var_names:
        # 1. Manual mapping
        if atlas_name in extra:
            canonical = extra[atlas_name]
            if canonical in spt_channels:
                atlas_to_spt[atlas_name] = canonical
                continue

        # 2. The atlas name itself might be an alias
        canonical = normalize_name(atlas_name, aliases)
        if canonical in spt_channels:
            atlas_to_spt[atlas_name] = canonical
            continue

        # 3. Case-insensitive exact match
        upper = atlas_name.upper()
        if upper in spt_channels_upper:
            atlas_to_spt[atlas_name] = spt_channels_upper[upper]
            continue

        # 4. HGNC normalization: atlas_name → HGNC symbol → SPT canonical
        if hgnc_spt_map:
            atlas_hgnc = hgnc_atlas_lookup.get(atlas_name, atlas_name)
            if atlas_hgnc in hgnc_spt_map:
                spt_ch = hgnc_spt_map[atlas_hgnc]
                atlas_to_spt[atlas_name] = spt_ch
                hgnc_match_count += 1
                logger.debug(
                    "  HGNC match: atlas '%s' → HGNC '%s' → SPT '%s'",
                    atlas_name, atlas_hgnc, spt_ch,
                )
                continue

    # Reverse: which SPT channels have no atlas match?
    matched_spt = set(atlas_to_spt.values())
    unmatched = spt_channels - matched_spt
    if unmatched:
        logger.warning("SPT channels with NO atlas match: %s", sorted(unmatched))

    if hgnc_cache_path is not None and hgnc_match_count > 0:
        logger.info(
            "HGNC normalization contributed %d additional matches "
            "(beyond manual/alias/case-insensitive tiers)",
            hgnc_match_count,
        )
    logger.info(
        "Atlas ↔ SPT mapping: %d matched (out of %d SPT channels)",
        len(matched_spt), len(spt_channels),
    )
    return atlas_to_spt


def load_atlas_subset(
    atlas_path: Path,
    atlas_columns: list[str],
    spt_names: list[str],
    max_cells: int | None = None,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, list[str]]:
    """
    Load specific columns from the atlas h5ad file into memory.

    Args:
        atlas_path: path to the h5ad file
        atlas_columns: atlas var_names to load (must exist in the file)
        spt_names: corresponding SPT canonical names (same length as atlas_columns)
        max_cells: if set, randomly sample this many cells
        rng: random number generator for sampling

    Returns:
        (X, spt_names_present) where X has shape (n_cells, len(atlas_columns))
    """
    logger.info("Loading %d atlas columns: %s", len(atlas_columns), atlas_columns)
    t0 = time.monotonic()
    adata = ad.read_h5ad(atlas_path, backed="r")
    n_total = adata.n_obs

    # Determine row indices to load
    if max_cells and n_total > max_cells:
        if rng is None:
            rng = np.random.default_rng(42)
        idx = rng.choice(n_total, size=max_cells, replace=False)
        idx.sort()
        logger.info(
            "Sampling %s / %s cells from atlas (%.1f%%)…",
            f"{max_cells:,}", f"{n_total:,}", 100 * max_cells / n_total,
        )
    else:
        idx = slice(None)
        logger.info("Loading all %s cells from atlas…", f"{n_total:,}")

    subset = adata[idx, atlas_columns]
    X = subset.X
    if sparse.issparse(X):
        X = X.toarray()
    else:
        X = np.asarray(X)

    adata.file.close()

    X = X.astype(np.float32)
    logger.info(
        "Atlas data loaded in %s — shape %s (%.1f MB)",
        format_elapsed(time.monotonic() - t0),
        X.shape,
        X.nbytes / 1024 ** 2,
    )
    return X, spt_names
