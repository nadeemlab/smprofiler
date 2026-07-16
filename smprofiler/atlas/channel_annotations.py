"""Channel annotation loading and alias normalization for atlas reference purposes.

Provides the identity/functional channel classification and alias resolution
used to reconcile marker names between SMProfiler studies and the atlas. This
is essentially manually maintained.

The smprofiler API (:func:`load_channel_annotations_from_api`) is intended to
be the canonical source for this information. Loading from the local pre-API
source files is deprecated, to ensure this information is always formatted in
just one way.

When loading from files, the files should be the JSONs as provided by the API.
"""
import json
import urllib.request
from pathlib import Path
from io import StringIO

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def load_channel_annotations_from_files(
    annotations_path: Path | StringIO,
    aliases_path: Path | StringIO,
) -> tuple[set, dict]:
    """
    Parse /channel-annotations/ and /channel-aliases/ .

    Returns:
        identity_channels: set of canonical identity channel names
        aliases: dict mapping alias → canonical name
    """
    if isinstance(aliases_path, StringIO):
        aliases = json.load(aliases_path)
    else:
        with open(aliases_path) as f:
            aliases = json.load(f)['aliases']

    if isinstance(annotations_path, StringIO):
        data = json.load(annotations_path)
    else:
        with open(annotations_path) as f:
            data = json.load(f)

    groups = data['channelGroups']
    identity_channels: set = set(groups['identity']['channels'])
    logger.info(
        'Channel annotations: %d identity, %d aliases',
        len(identity_channels), len(aliases),
    )
    return identity_channels, aliases


def load_channel_annotations_from_api(
    base_url: str,
    timeout: int = 30,
) -> tuple[set, dict]:
    """
    Fetch channel annotations from the smprofiler API,
    ``/channel-annotations/`` and ``/channel-aliases/``.

    Returns the same as load_channel_annotations_from_file().
    """
    base = base_url.rstrip('/')

    def _get_and_fill_buffer(url: str) -> StringIO:
        f = StringIO()
        request = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            f.write(response.read().decode())
        return f

    annotations_url = f'{base}/channel-annotations/'
    aliases_url = f'{base}/channel-aliases/'

    logger.info('Fetching channel annotations from API: %s', annotations_url)
    annotations_file = _get_and_fill_buffer(annotations_url)
    logger.info('Fetching channel aliases from API: %s', aliases_url)
    aliases_file = _get_and_fill_buffer(aliases_url)
    return load_channel_annotations_from_files(annotations_file, aliases_file)


def normalize_name(name: str, aliases: dict) -> str:
    """Resolve a channel name to its canonical form via the aliases map."""
    return aliases.get(name, name)

