"""Count cells for a specific signature, over the specially-created binary-format index."""

from typing import cast

from numpy import sum
from numpy import uint64 as np_int64
from numpy.typing import NDArray

from smprofiler.ondemand.computers.cell_data_arrays import CellDataArrays
from smprofiler.ondemand.relevant_specimens import retrieve_cells_selected
from smprofiler.ondemand.computers.generic_job_computer import GenericJobComputer
from smprofiler.ondemand.phenotype_str import phenotype_str_to_phenotype
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class CountsComputer(GenericJobComputer):
    """Scan binary-format expression matrices for specific signatures."""

    def compute(self) -> None:
        args, arrays = self._prepare_parameters()
        if arrays.identifiers is None:
            self.handle_insert_value(None, allow_null=True)
        else:
            count = self._perform_count(args, arrays)
            self.handle_insert_value(count)

    def _prepare_parameters(self) -> tuple[tuple[int, int, tuple[int, ...]], CellDataArrays]:
        study = self.job.study
        specification = str(self.job.feature_specification)
        _, specifiers = self.retrieve_specifiers(self.connection, study, specification)
        phenotype = phenotype_str_to_phenotype(specifiers[0])
        cells_selected = retrieve_cells_selected(self.connection, study, specification)  # to deprecate
        marker_set = (phenotype.positive_markers, phenotype.negative_markers)
        arrays = self.get_cell_data_arrays()
        features = tuple(n.symbol for n in arrays.feature_names.names)
        signatures = tuple(map(lambda m: cast(int, self._compute_signature(m, features)), marker_set))
        return ((signatures[0], signatures[1], cells_selected), arrays)

    @staticmethod
    def _perform_count(args: tuple[int, int, tuple[int, ...]], arrays: CellDataArrays) -> int:
        if arrays.identifiers.shape[0] == 0:
            return 0
        return CountsComputer._count_structures_of_partial_signed_signature(*args, arrays)

    @staticmethod
    def _count_structures_of_partial_signed_signature(
        positives_signature: int,
        negatives_signature: int,
        cells_selected: tuple[int, ...],
        arrays: CellDataArrays,
    ) -> int:
        """Count the number of cells in the given sample that match this signature."""
        if positives_signature == 0 and negatives_signature == 0:
            return arrays.identifiers.shape[0]
        count = CountsComputer._get_count(arrays.phenotype, positives_signature, negatives_signature)
        return count

    @staticmethod
    def _get_count(array_phenotype: NDArray[np_int64], positives_mask: int, negatives_mask: int) -> int:
        """
        Counts the number of elements of the list of integer-represented binary numbers which equal
        to 1 along the bits indicated by the positives mask, and equal to 0 along the bits indicated
        by the negatives mask.
        """
        return sum((array_phenotype | positives_mask == array_phenotype) &
                   (~array_phenotype | negatives_mask == ~array_phenotype))

    @staticmethod
    def _compute_signature(
        channel_names: tuple[str, ...],
        all_features: tuple[str, ...],
    ) -> int:
        """Compute int signature of this channel name combination."""
        missing = set(channel_names).difference(all_features)
        if len(missing) > 0:
            message = f'Cannot compute signature when these columns are requested: {missing}. Only have: {all_features}'
            raise ValueError(message)
        signature = 0
        indices = map(lambda name: all_features.index(name), channel_names)
        for index in indices:
            signature = signature + (1 << index)
        return signature

