"""HGNC gene-symbol normalization.

Resolves gene/channel names to their HGNC-approved symbols via mygene.info
and the HGNC REST API, caching results on disk for offline reuse.

This is an optional aid for reconciling atlas marker names with SPT channel
names when no complete manual mapping is available. When a complete manual
mapping exists (see ``--atlas-mapping`` / the manual tier of
``build_atlas_channel_map``), this normalization is not required and can be
disabled by not supplying an HGNC cache path.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def normalize_names_to_hgnc(
    names: list[str],
    cache_path: Path,
    timeout: int = 30,
) -> dict[str, str]:
    """
    Resolve a list of gene/channel names to their HGNC-approved symbols.

    Strategy:
    1. Load existing cache from disk (JSON: {original: hgnc_approved_symbol}).
    2. For uncached names, batch-query mygene.info POST /v3/query.
    3. For names still unresolved, try HGNC REST API per-symbol.
    4. Persist the updated cache to disk for future offline use.

    Returns a dict mapping each input name to its HGNC-approved symbol.
    Names with no authoritative match are mapped to themselves (identity).
    """
    # Load existing cache
    cache: dict[str, str] = {}
    if cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)
        logger.info("HGNC cache: loaded %d entries from %s", len(cache), cache_path)
    else:
        logger.info("HGNC cache not found at %s — will query APIs", cache_path)

    to_resolve = [n for n in names if n not in cache]
    if not to_resolve:
        logger.info("All %d names found in HGNC cache (no network calls needed)", len(names))
        return {n: cache.get(n, n) for n in names}

    logger.info(
        "Resolving %d names via HGNC normalization (%d already cached)",
        len(to_resolve), len(cache),
    )

    # --- mygene.info batch query ---
    def _mygene_batch(symbols: list[str]) -> dict[str, str]:
        """Return {input_symbol: hgnc_approved_symbol} for resolved entries."""
        url = "https://mygene.info/v3/query"
        body = json.dumps({
            "q": list(symbols),
            "fields": "symbol",
            "species": "human",
            "scopes": "symbol",
        }).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("mygene.info batch query failed: %s", exc)
            return {}
        # Batch POST returns a list — one entry per query symbol
        if not isinstance(data, list):
            data = data.get("hits", [])
        result: dict[str, str] = {}
        for hit in data:
            if not isinstance(hit, dict) or hit.get("notfound"):
                continue
            approved = hit.get("symbol")
            query_sym = hit.get("query", "")
            if approved and query_sym:
                result[query_sym] = approved
        return result

    def _hgnc_single(symbol: str) -> str | None:
        """Try HGNC REST API for a single symbol; returns approved symbol or None."""
        encoded = urllib.parse.quote(symbol)
        url = f"https://rest.genenames.org/search/symbol/{encoded}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode()
            data = json.loads(raw)
        except (urllib.error.URLError, OSError) as exc:
            logger.debug("HGNC REST query failed for '%s': %s", symbol, exc)
            return None
        except json.JSONDecodeError as exc:
            logger.debug("HGNC REST returned non-JSON for '%s': %s", symbol, exc)
            return None
        docs = data.get("response", {}).get("docs", [])
        return docs[0].get("symbol") if docs else None

    # mygene.info batch (process in chunks of 500)
    mygene_resolved: dict[str, str] = {}
    batch_size = 500
    for i in range(0, len(to_resolve), batch_size):
        batch = to_resolve[i: i + batch_size]
        resolved = _mygene_batch(batch)
        mygene_resolved.update(resolved)
        logger.info(
            "mygene.info: resolved %d/%d names in batch [%d:%d]",
            len(resolved), len(batch), i, i + len(batch),
        )

    # HGNC REST fallback for names mygene didn't resolve
    still_unresolved = [n for n in to_resolve if n not in mygene_resolved]
    hgnc_resolved: dict[str, str] = {}
    if still_unresolved:
        logger.info("HGNC REST fallback for %d unresolved names…", len(still_unresolved))
        for sym in still_unresolved:
            approved = _hgnc_single(sym)
            if approved and approved != sym:
                hgnc_resolved[sym] = approved
                logger.debug("  HGNC REST: '%s' → '%s'", sym, approved)

    # Merge results into cache (mygene takes precedence over HGNC REST)
    for sym in to_resolve:
        if sym in mygene_resolved:
            cache[sym] = mygene_resolved[sym]
        elif sym in hgnc_resolved:
            cache[sym] = hgnc_resolved[sym]
        else:
            cache[sym] = sym  # no authoritative symbol found; keep original

    # Persist updated cache
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
    logger.info("HGNC cache saved: %s (%d total entries)", cache_path, len(cache))

    changed = {sym: cache[sym] for sym in to_resolve if cache[sym] != sym}
    logger.info(
        "HGNC normalization: %d/%d newly resolved names mapped to a different symbol",
        len(changed), len(to_resolve),
    )
    if changed:
        for orig, approved in sorted(changed.items()):
            logger.debug("  '%s' → '%s'", orig, approved)

    return {n: cache.get(n, n) for n in names}
