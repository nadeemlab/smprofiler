"""
Per-study ordered channel (marker) retrieval. Also splits the discovered channels
into identity / functional lists according to the global channel annotation groups.
"""
from urllib import request
from urllib.parse import quote_plus
import json

from attrs import define

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.cache import StandaloneSQLiteHTTPCache
from smprofiler.atlas.channel_annotations import normalize_name
from smprofiler.db.exchange_data_formats.metrics import Channel

logger = colorized_logger(__name__)

@define
class StudyChannel:
    study_specific: str
    smprofiler_normalized: str
    atlas_specific: str

@define
class StudyOrderedChannels:
    identity: tuple[StudyChannel, ...]
    functional: tuple[StudyChannel, ...]

def _retrieve_study_channels_from_api(
    study: str,
    identity_channels: tuple[str, ...],
    aliases: dict[str, str],
    smprofiler_to_atlas: dict[str, str],
    base_url: str,
    timeout: int = 30,
) -> StudyOrderedChannels:
    base = base_url.rstrip('/')
    url = f'{base}/channels/?study={quote_plus(study)}'
    response_body = StandaloneSQLiteHTTPCache.retrieve_response(url)
    if response_body is None:
        r = request.Request(url, headers={'Accept': 'application/json'})
        with request.urlopen(r, timeout=timeout) as response:
            response_body = response.read()
            StandaloneSQLiteHTTPCache.cache_response(url, response_body)
    x = json.loads(response_body.decode())
    data: list[Channel] = [Channel.model_validate_json(json.dumps(item)) for item in x]
    channels = []
    for c in data:
        study_specific = c.symbol
        smprofiler_normalized = normalize_name(study_specific, aliases)
        atlas_specific = smprofiler_to_atlas.get(smprofiler_normalized, None)
        if atlas_specific is None:
            logger.warning(
                f'Could not resolve study_specific="{study_specific}" or smprofiler_normalized={smprofiler_normalized} to atlas name.'
            )
            continue
        channels.append(StudyChannel(study_specific, smprofiler_normalized, atlas_specific))
    identity = tuple(filter(lambda c: c.smprofiler_normalized in identity_channels, channels))
    functional = tuple(filter(lambda c: c.smprofiler_normalized not in identity_channels, channels))
    return StudyOrderedChannels(identity, functional)

def retrieve_all_study_channels_from_api(
    studies: tuple[str, ...],
    *args,
    **kwargs,
) -> tuple[StudyOrderedChannels, ...]:
    return tuple(map(
        lambda study: _retrieve_study_channels_from_api(study, *args, **kwargs),
        studies,
    ))


