from pathlib import Path
from enum import Enum
from typing import Literal

from attrs import define

from smprofiler.db.exchange_data_formats.atlas_models import InherenceAtlasAnnotatedChannel


@define
class TrainingScenarioStudy:
    study_handle: str
    channels: tuple[InherenceAtlasAnnotatedChannel, ...]

    def get_channels(self, group: str) -> tuple[InherenceAtlasAnnotatedChannel, ...]:
        return tuple(filter(lambda c: c.inherence == group, self.channels))


@define
class TrainingOptions:
    output_directory: Path
    max_cells: int | None
    cv_folds: int
    database_config_file: Path
    parquet_atlas_path: Path


class CellAtlasSource(Enum):
    ALLEN_IMMUNE_HEALTH = 'Allen Immune Health 2025'


@define
class InherenceAtlasAnnotatedChannel:
    """
    'Inherence' refers to whether a marker represents an inherent
    feature of a given cell, i.e. it is a cell identity marker,
    or on the contrary it indicates a functional, mutable state.

    A marker/channel represented with this object is regarded
    in relation to a specific *atlas* in which it may (approximately) appear
    as an available gene, and a specific *study* in which it
    has been measured.
    """
    study_specific_name: str
    atlas_specific_name: str
    inherence: Literal['identity', 'functional']

