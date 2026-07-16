"""Per-study channel discovery.

Locates channel-definition files inside each study's dataset directory and
splits the discovered channels into identity / functional lists according to
the global channel annotation groups.
"""
from pathlib import Path
from urllib import request
from urllib.parse import quote_plus

import pandas as pd
from attrs import define

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.atlas.channel_annotations import normalize_name
from smprofiler.db.exchange_data_formats.metrics import Channel

logger = colorized_logger(__name__)

@define
class StudyOrderedChannels:
    identity: tuple[str, ...]
    functional: tuple[str, ...]

def _read_channel_names_from_file(path: Path, aliases: dict) -> list[str]:
    """
    Read channel names from an elementary_phenotypes or channels file.

    Handles:
    - CSV / TSV with 'Symbol' column  (elementary_phenotypes_overlay.csv)
    - CSV / TSV with 'Name' column    (elementary_phenotypes.csv, channels.tsv)
    """
    sep = "\t" if path.suffix == ".tsv" else ","
    try:
        df = pd.read_csv(path, sep=sep)
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return []

    col = None
    for candidate in ("Symbol", "Name"):
        if candidate in df.columns:
            col = candidate
            break

    if col is None:
        logger.warning("No 'Symbol' or 'Name' column in %s (columns: %s)", path, list(df.columns))
        return []

    names = []
    for raw in df[col].dropna():
        canonical = normalize_name(str(raw).strip(), aliases)
        names.append(canonical)
    logger.debug("  %s: %d channel names read (column '%s')", path.name, len(names), col)
    return names


def _retrieve_study_channels_from_api(
    study: str,
    identity_channels: tuple[str, ...],
    aliases: dict[str, str],
    base_url: str,
    timeout: int = 30,
) -> StudyOrderedChannels:
    base = base_url.rstrip('/')
    url = f'{base}/channels/?study={quote_plus(study)}'
    r = request.Request(url, headers={'Accept': 'application/json'})
    with request.urlopen(r, timeout=timeout) as response:
        data: list[Channel] = response.read().decode()
    names = tuple(map(lambda c: normalize_name(c.symbol, aliases), data))
    identity = tuple(filter(lambda n: n in identity_channels, names))
    functional = tuple(filter(lambda n: n not in identity_channels, names))
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


def discover_study_channels(
    datasets_dir: Path,
    studies: list[str],
    identity_channels: set,
    aliases: dict,
) -> dict[str, dict]:
    """
    For each study, locate channel definition files and split into identity /
    functional lists based on the global channel annotation groups.

    Returns:
        dict mapping study_name → {
            "identity": [channel, ...],
            "functional": [channel, ...],
        }
    """

    results = {}
    for study_name in studies:
        study_dir = datasets_dir / study_name
        if not study_dir.is_dir():
            logger.warning("Dataset directory not found: %s", study_dir)
            continue

        all_names: list[str] = []
        pattern = '**/generated_artifacts/elementary_phenotypes.csv'
        files = sorted(study_dir.glob(pattern))
        for f in files:
            names = _read_channel_names_from_file(f, aliases)
            all_names.extend(names)
        if all_names:
            break  # stop searching once we found something

        if not all_names:
            logger.warning("No channel files found for study '%s' – skipping", study_name)
            continue

        # Deduplicate while preserving order
        seen: set = set()
        unique_names = []
        for n in all_names:
            if n not in seen:
                seen.add(n)
                unique_names.append(n)

        logger.info(
            "Study '%s': %d unique channels in dataset files",
            study_name, len(unique_names),
        )
        identity = [n for n in unique_names if n in identity_channels]
        functional = [n for n in unique_names if n in functional_channels]

        if not identity:
            logger.warning("Study '%s': no identity channels found, skipping", study_name)
            continue
        if not functional:
            logger.warning("Study '%s': no functional channels found, skipping", study_name)
            continue

        results[study_name] = {"identity": identity, "functional": functional}
        logger.info(
            "Study '%s': %d identity channels, %d functional channels",
            study_name, len(identity), len(functional),
        )
        logger.debug("  Identity:   %s", identity)
        logger.debug("  Functional: %s", functional)

    return results
