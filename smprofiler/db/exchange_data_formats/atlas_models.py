from datetime import datetime

from pydantic import BaseModel


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

