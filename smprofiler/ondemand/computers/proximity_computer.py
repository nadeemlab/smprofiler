"""Proximity calculation from pairs of signatures."""

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.ondemand.phenotype_str import phenotype_str_to_phenotype
from smprofiler.ondemand.computers.generic_job_computer import GenericJobComputer
from smprofiler.ondemand.computers.cell_data_arrays import CellDataArrays
from smprofiler.workflow.common.proximity import \
    compute_proximity_metric_for_signature_pair
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class ProximityComputer(GenericJobComputer):
    """Do proximity calculation from pair of signatures."""

    def compute(self) -> None:
        if self.handle_excessive_sample_size('CELL_NUMBER_LIMIT_PROXIMITY', 750000):
            return
        args, arrays = self._prepare_parameters()
        if arrays.identifiers is None:
            self.handle_insert_value(None, allow_null=True)
        else:
            value = self._perform_computation(args, arrays)
            self.handle_insert_value(value, allow_null=True)

    def _prepare_parameters(
        self,
    ) -> tuple[tuple[PhenotypeCriteria, PhenotypeCriteria, float], CellDataArrays]:
        study = self.job.study
        feature_specification = str(self.job.feature_specification)
        _, specifiers = ProximityComputer.retrieve_specifiers(self.connection, study, feature_specification)
        phenotype1 = phenotype_str_to_phenotype(specifiers[0])
        phenotype2 = phenotype_str_to_phenotype(specifiers[1])
        radius = float(specifiers[2])
        arrays = self.get_cell_data_arrays()
        return (phenotype1, phenotype2, radius), arrays

    def _perform_computation(self, args: tuple, arrays: CellDataArrays) -> float | None:
        phenotype1, phenotype2, radius = args
        return compute_proximity_metric_for_signature_pair(
            phenotype1,
            phenotype2,
            radius,
            arrays.phenotype,
            arrays.location,
            arrays.feature_names,
        )
