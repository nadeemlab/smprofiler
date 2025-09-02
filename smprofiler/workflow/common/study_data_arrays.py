"""Data type for compressed expressions."""

StudyDataArrays = dict[
    str,
    dict[str, str] |
    dict[str, int] |
    dict[str, dict[int, int]] |
    dict[str, dict[int, list[float]]]
]
