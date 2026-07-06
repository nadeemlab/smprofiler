"""Automatic (heuristic) atlas ↔ SPT channel mapping.

Reconstructs a mapping between atlas feature names and canonical SPT channel
names by tiered heuristics (manual overrides, aliases, case-insensitive match,
HGNC-symbol normalization). This is the fallback for datasets that lack a
complete manual mapping.

When a manual mapping exists — as produced by the atlas aggregation step and
loaded via :func:`smprofiler.atlas.atlas_data.load_channel_mapping` — that
manual mapping is authoritative and this module is not used. It is retained
for future datasets without such a mapping (and is the sole consumer of
:mod:`smprofiler.atlas.hgnc_normalization`).
"""
from pathlib import Path

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.channel_annotations import normalize_name
from smprofiler.atlas.hgnc_normalization import normalize_names_to_hgnc

logger = colorized_logger(__name__)


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
