from pathlib import Path
from enum import Enum
from typing import Literal

from numpy.typing import NDArray
from sklearn.pipeline import Pipeline

from attrs import define


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


@define
class TrainingScenarioStudy:
    study_handle: str
    channels: tuple[InherenceAtlasAnnotatedChannel, ...]

    def get_channels(self, group: str) -> tuple[InherenceAtlasAnnotatedChannel, ...]:
        return tuple(filter(lambda c: c.inherence == group, self.channels))

    def get_channels_study_specific_strs(self, group: str) -> tuple[InherenceAtlasAnnotatedChannel, ...]:
        return tuple(map(
            lambda c: c.study_specific_name,
            filter(lambda c: c.inherence == group, self.channels),
        ))


TrainingPlan = tuple[TrainingScenarioStudy, ...]


@define
class TrainingOptions:
    output_directory: Path
    max_cells: int | None
    cv_folds: int
    database_config_file: Path
    parquet_atlas_path: Path


@define
class TrainingProgress:
    model_counter: int
    number_validated: int
    number_validated_std: int
    summary_rows: list[dict]
    model_records: list[dict]


@define
class Splits:
    test_indices: NDArray
    x_train: NDArray
    x_test: NDArray
    y_train: NDArray
    y_test: NDArray
    target_channel: str
    target_column: int


@define
class SelectedModel:
    model: Pipeline
    name: str
    cv_r2: float
    cv_r2_std: float
    training_time_formatted: str
    training_time_seconds: float
    test_r2: float
    test_mae: float
    global_std: float


STD_METHODS = {
    'bayesian_ridge': 'bayesian_posterior',
    'random_forest': 'tree_ensemble_spread',
    'extra_trees': 'tree_ensemble_spread',
}

