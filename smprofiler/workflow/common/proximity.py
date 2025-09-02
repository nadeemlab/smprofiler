"""Low-level calculations of proximity metric."""

from math import isnan

from sklearn.neighbors import BallTree  # type: ignore

from numpy import array
from numpy import sum
from numpy import concatenate
from numpy import uint64 as np_int64
from numpy.typing import NDArray

from smprofiler.ondemand.computers.counts_computer import CountsComputer
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.accessors.cells import BitMaskFeatureNames
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def compute_proximity_metric_for_signature_pair(
    phenotype1: PhenotypeCriteria,
    phenotype2: PhenotypeCriteria,
    radius: float,
    phenotype_masks: NDArray[np_int64],
    locations: NDArray[np_int64],
    feature_names: BitMaskFeatureNames,
) -> float | None:
    features = tuple(n.symbol for n in feature_names.names)
    def signature(markers: tuple[str, ...]):
        return CountsComputer._compute_signature(markers, features)

    marker_set1 = (phenotype1.positive_markers, phenotype1.negative_markers)
    signatures1 = array(tuple(map(signature, marker_set1)), dtype=np_int64)

    marker_set2 = (phenotype2.positive_markers, phenotype2.negative_markers)
    signatures2 = array(tuple(map(signature, marker_set2)), dtype=np_int64)

    mask1 = ((phenotype_masks | signatures1[0]) == phenotype_masks) & \
        ((~phenotype_masks | signatures1[1]) == ~phenotype_masks)
    mask2 = ((phenotype_masks | signatures2[0]) == phenotype_masks) & \
        ((~phenotype_masks | signatures2[1]) == ~phenotype_masks)

    locations1 = locations[:, mask1]
    mask12_size = sum(mask1 & mask2)
    source_count = locations1.shape[1]
    if source_count == 0:
        logger.debug(f'No elements matching mask: {marker_set1} {signatures1} {tuple(bin(s) for s in signatures1)}')
        return None
    tree = BallTree(locations.transpose())
    within_radius_indices_list = tree.query_radius(locations1.transpose(), radius, return_distance=False)
    count = sum(mask2[concatenate(within_radius_indices_list)]) - mask12_size
    return count / source_count


def _validate_value(value) -> bool:
    if (not isinstance(value, float)) and (not isinstance(value, int)):
        return False
    if value is None:
        return False
    if isnan(value):
        return False
    return True


def stage_proximity_feature_values(
    feature_uploader,
    feature_values,
    sample_identifier,
) -> None:
    for _, row in feature_values.iterrows():
        specifiers = (
            row['Phenotype 1'],
            row['Phenotype 2'],
            row['Pixel radius'],
        )
        value = row['Proximity']
        if _validate_value(value):
            feature_uploader.stage_feature_value(specifiers, sample_identifier, value)
