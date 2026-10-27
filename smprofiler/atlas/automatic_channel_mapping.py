"""Automatic (heuristic) atlas-to-SMProfiler channel mapping.

Reconstructs a mapping between atlas feature names and SMProfiler database channel
names by tiered heuristics (manual overrides, aliases, case-insensitive match,
HGNC-symbol normalization). This is the fallback for datasets that lack a
complete manual mapping.

When a manual mapping exists, as produced by the atlas aggregation step and
loaded via `load_channel_mapping`, that manual mapping is authoritative and
this module is not used. It is retained for future datasets without such a
mapping (and is the sole consumer of `smprofiler.atlas.hgnc_normalization`).
"""
from pathlib import Path

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.channel_annotations import normalize_name
from smprofiler.atlas.hgnc_normalization import normalize_names_to_hgnc

logger = colorized_logger(__name__)


def build_atlas_channel_map(
    atlas_var_names: list[str],
    smprofiler_channels: set,
    aliases: dict,
    extra_mapping: dict | None = None,
    hgnc_cache_path: Path | None = None,
) -> dict[str, str]:
    """
    Build a mapping: atlas_var_name to canonical SMProfiler channel name.

    Resolution order:
    1. Extra manual mapping (channel_name_mapping.json)
    2. Alias lookup (e.g. atlas has 'CD8A', SMProfiler has 'CD8' via alias CD8A => CD8)
    3. Exact case-insensitive match
    4. HGNC normalization: both atlas name and SMProfiler name normalized to the HGNC
       approved symbol; match on that shared canonical form. Only fires if
       hgnc_cache_path is provided.

    Returns dict of {atlas_var_name: smprofiler_canonical_name} for matched entries only.
    """
    extra = extra_mapping or {}

    smprofiler_channels_upper = {c.upper(): c for c in smprofiler_channels}

    hgnc_smprofiler_map: dict[str, str] = {}
    hgnc_atlas_lookup: dict[str, str] = {}
    if hgnc_cache_path is not None:
        all_names_for_hgnc = list(atlas_var_names) + list(smprofiler_channels)
        hgnc_norm = normalize_names_to_hgnc(all_names_for_hgnc, hgnc_cache_path)

        for smprofiler_ch in smprofiler_channels:
            h = hgnc_norm.get(smprofiler_ch, smprofiler_ch)
            if (h is not None) and (h not in hgnc_smprofiler_map):
                hgnc_smprofiler_map[h] = smprofiler_ch

        for atlas_name in atlas_var_names:
            hgnc_atlas_lookup[atlas_name] = hgnc_norm.get(atlas_name, atlas_name)

    atlas_to_smprofiler: dict[str, str] = {}
    hgnc_match_count = 0
    for atlas_name in atlas_var_names:
        if atlas_name in extra:
            canonical = extra[atlas_name]
            if canonical in smprofiler_channels:
                atlas_to_smprofiler[atlas_name] = canonical
                continue

        canonical = normalize_name(atlas_name, aliases)
        if canonical in smprofiler_channels:
            atlas_to_smprofiler[atlas_name] = canonical
            continue

        upper = atlas_name.upper()
        if upper in smprofiler_channels_upper:
            atlas_to_smprofiler[atlas_name] = smprofiler_channels_upper[upper]
            continue

        if hgnc_smprofiler_map:
            atlas_hgnc = hgnc_atlas_lookup.get(atlas_name, atlas_name)
            if atlas_hgnc in hgnc_smprofiler_map:
                smprofiler_ch = hgnc_smprofiler_map[atlas_hgnc]
                atlas_to_smprofiler[atlas_name] = smprofiler_ch
                hgnc_match_count += 1
                logger.debug(
                    "  HGNC match: atlas '%s' → HGNC '%s' → SMProfiler '%s'",
                    atlas_name, atlas_hgnc, smprofiler_ch,
                )
                continue

    matched_smprofiler = set(atlas_to_smprofiler.values())
    unmatched = smprofiler_channels - matched_smprofiler
    if unmatched:
        logger.warning("SMProfiler channels with NO atlas match: %s", sorted(unmatched))

    if hgnc_cache_path is not None and hgnc_match_count > 0:
        logger.info(
            "HGNC normalization contributed %d additional matches "
            "(beyond manual/alias/case-insensitive tiers)",
            hgnc_match_count,
        )
    logger.info(
        "Atlas to SMProfiler mapping: %d matched (out of %d SMProfiler channels)",
        len(matched_smprofiler), len(smprofiler_channels),
    )
    return atlas_to_smprofiler

