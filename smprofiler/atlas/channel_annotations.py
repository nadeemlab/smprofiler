"""Channel annotation loading and alias normalization for atlas reference purposes.

Provides the identity/functional channel classification and alias resolution
used to reconcile marker names between SMProfiler studies and the atlas. This
is essentially manually maintained.

The smprofiler API (:func:`load_channel_annotations_from_api`) is intended to
be the canonical source for this information. Loading from the local pre-API
source files is deprecated, to ensure this information is always formatted in
just one way.

When loading from files, the files should be the JSONs as provided by the API
server.
"""
import json
import urllib.request
from pathlib import Path
from io import StringIO

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def load_channel_annotations_from_files(
    annotations: Path | StringIO,
    aliases: Path | StringIO,
) -> tuple[set, dict[str, str]]:
    """
    Parse ``/channel-annotations/`` and ``/channel-aliases/`` responses.

    Returns:
        identity_channels: set of canonical identity channel names
        aliases: dict mapping alias → canonical name
    """
    if isinstance(aliases, StringIO):
        aliases_data = json.load(aliases)['aliases']
    else:
        with open(aliases) as f:
            aliases_data = json.load(f)['aliases']

    if isinstance(annotations, StringIO):
        data = json.load(annotations)
    else:
        with open(annotations) as f:
            data = json.load(f)

    groups = data['channelGroups']
    identity_channels: set = set(groups['identity']['channels'])
    logger.info(
        'Channel annotations: %d identity, %d aliases',
        len(identity_channels), len(aliases_data),
    )
    return identity_channels, aliases_data


def load_channel_annotations_from_api(
    base_url: str,
    timeout: int = 30,
    ) -> tuple[set, dict[str, str]]:
    """
    Fetch channel annotations from the smprofiler API, ``/channel-annotations/``
    and ``/channel-aliases/``.

    Returns the same as load_channel_annotations_from_file.
    """
    base = base_url.rstrip('/')

    annotations_url = f'{base}/channel-annotations/'
    aliases_url = f'{base}/channel-aliases/'

    logger.info('Fetching channel annotations from API: %s', annotations_url)
    annotations_file = _get_and_fill_buffer(annotations_url, timeout)
    logger.info('Fetching channel aliases from API: %s', aliases_url)
    aliases_file = _get_and_fill_buffer(aliases_url, timeout)
    return load_channel_annotations_from_files(annotations_file, aliases_file)

def _get_and_fill_buffer(url: str, timeout: int) -> StringIO:
    f = StringIO()
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        f.write(response.read().decode())
    f.seek(0)
    return f


def normalize_name(name: str, aliases: dict) -> str:
    """Resolve a channel name to its canonical form via the aliases map."""
    return aliases.get(name, name)

