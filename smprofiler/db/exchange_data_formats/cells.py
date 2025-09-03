"""Data structure to represent all cell data for one sample."""

from pydantic import BaseModel  # pylint: disable=no-name-in-module

from smprofiler.db.exchange_data_formats.metrics import Channel

CellsData = bytes

class BitMaskFeatureNames(BaseModel):
    """
    The ordered list of channels corresponding to the binary format bit mask representation of a
    cell's channel positivity/negativity assignments.
    """
    names: tuple[Channel, ...]
