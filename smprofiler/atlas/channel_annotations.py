"""Channel annotation loading and alias normalization.

Provides the identity/functional channel classification and alias resolution
used to reconcile marker names between SPT studies and the atlas. The smprofiler
API (:func:`load_channel_annotations_from_api`) is the source of truth; loading
from a local JSON file (:func:`load_channel_annotations`) is deprecated, so that
training never runs against annotations that are stale relative to the live
service. HGNC-symbol normalization lives in
:mod:`smprofiler.atlas.hgnc_normalization`.
"""
import json
import urllib.request
import warnings
from pathlib import Path

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def load_channel_annotations(annotations_path: Path) -> tuple[set, set, dict]:
    """
    Parse channel_annotations.json.

    .. deprecated::
        Load channel annotations from the smprofiler API via
        :func:`load_channel_annotations_from_api` instead. A local file can be
        stale relative to the live service, causing training to run against
        annotations that no longer match production.

    Returns:
        identity_channels: set of canonical identity channel names
        functional_channels: set of canonical functional channel names
        aliases: dict mapping alias → canonical name (for channels only)
    """
    warnings.warn(
        "load_channel_annotations (local file) is deprecated; load channel "
        "annotations from the smprofiler API via load_channel_annotations_from_api.",
        DeprecationWarning,
        stacklevel=2,
    )
    with open(annotations_path) as f:
        data = json.load(f)

    groups = data["groups"]
    identity_channels: set = set(groups["identity"]["channels"])

    functional_channels: set = set()
    for group_name, group_data in groups.items():
        if group_name != "identity":
            functional_channels.update(group_data["channels"])

    all_channels = identity_channels | functional_channels

    # Filter aliases to channel aliases only (aliases also contains cell type strings)
    aliases = {}
    for alias, canonical in data.get("aliases", {}).items():
        if isinstance(canonical, str) and canonical in all_channels:
            aliases[alias] = canonical

    logger.info(
        "Channel annotations: %d identity, %d functional, %d aliases",
        len(identity_channels), len(functional_channels), len(aliases),
    )
    return identity_channels, functional_channels, aliases


def load_channel_annotations_from_api(
    base_url: str,
    timeout: int = 30,
) -> tuple[set, set, dict]:
    """
    Fetch channel annotations from the smprofiler API.

    Calls:
        GET {base_url}/channel-annotations/
        GET {base_url}/channel-aliases/

    Returns the same (identity_channels, functional_channels, aliases) tuple
    as load_channel_annotations().
    """
    base = base_url.rstrip("/")

    def _get_json(url: str) -> dict:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    annotations_url = f"{base}/channel-annotations/"
    aliases_url = f"{base}/channel-aliases/"

    logger.info("Fetching channel annotations from API: %s", annotations_url)
    ann_data = _get_json(annotations_url)
    logger.info("Fetching channel aliases from API: %s", aliases_url)
    ali_data = _get_json(aliases_url)

    channel_groups: dict = ann_data.get("channelGroups", {})
    identity_channels: set = set(channel_groups.get("identity", {}).get("channels", []))

    functional_channels: set = set()
    for group_name, group_data in channel_groups.items():
        if group_name != "identity":
            functional_channels.update(group_data.get("channels", []))

    all_channels = identity_channels | functional_channels

    raw_aliases: dict = ali_data.get("aliases", {})
    aliases = {
        alias: canonical
        for alias, canonical in raw_aliases.items()
        if isinstance(canonical, str) and canonical in all_channels
    }

    logger.info(
        "Channel annotations (API): %d identity, %d functional, %d aliases",
        len(identity_channels), len(functional_channels), len(aliases),
    )
    return identity_channels, functional_channels, aliases


def normalize_name(name: str, aliases: dict) -> str:
    """Resolve a channel name to its canonical form via the aliases map."""
    return aliases.get(name, name)
