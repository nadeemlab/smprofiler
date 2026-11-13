from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel
from attrs import define


class AtlasModelMetadata(BaseModel):
    """Description of one trained atlas-reference model (without the ONNX model itself).

    The ONNX graph takes raw identity intensities `X` (columns in `input_channels` order)
    and the raw `measured` target intensity, and returns `z`, `mean`, `std` per cell.
    """
    id: int
    study: str | None
    target_channel: str
    input_channels: list[str]
    architecture_type: str
    std_method: str
    onnx_input_dtype: str
    onnx_has_std: bool
    atlas_version: str | None
    cv_r2: float | None
    test_r2: float | None
    test_mae: float | None
    n_train: int | None
    n_test: int | None
    training_time_seconds: float | None
    size_bytes: int | None
    created: datetime


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

