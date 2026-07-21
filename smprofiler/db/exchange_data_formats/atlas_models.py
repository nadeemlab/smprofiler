from datetime import datetime

from pydantic import BaseModel


class AtlasModelMetadata(BaseModel):
    """Description of one trained atlas-reference model (without the ONNX bytes).

    Returned by the ``/atlas-models/`` endpoint. Download the model itself from
    ``/atlas-model/`` using ``id`` (or by ``study`` + ``target_channel``). To run
    it, feed inputs of dtype ``onnx_input_dtype`` in ``input_channels`` order. When
    ``onnx_has_std`` is true the ONNX graph has two outputs — the expected
    intensity (index 0) and a per-sample predictive std (index 1) — which inference
    combines into a z-score.
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
