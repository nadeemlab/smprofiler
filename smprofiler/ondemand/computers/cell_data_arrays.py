
from numpy import uint64 as np_int64
from numpy.typing import NDArray
from attrs import define

from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames

@define
class CellDataArrays:
    """Represents the location and phenotypes for the cells in one sample."""
    location: NDArray[np_int64]
    phenotype: NDArray[np_int64]
    feature_names: BitMaskFeatureNames
    identifiers: NDArray[np_int64]
