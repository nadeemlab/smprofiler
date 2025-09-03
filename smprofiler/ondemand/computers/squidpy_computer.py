"""Selected metrics from the squidpy library, adapted for use with SMProfiler."""

from typing import cast

from pandas import DataFrame  # type: ignore

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.ondemand.phenotype_str import phenotype_str_to_phenotype
from smprofiler.apiserver.request_scheduling.computation_scheduler import retrieve_feature_derivation_method
from smprofiler.ondemand.computers.generic_job_computer import GenericJobComputer
from smprofiler.ondemand.computers.cell_data_arrays import CellDataArrays
from smprofiler.workflow.common.squidpy import (
    lookup_squidpy_feature_class,
    compute_squidpy_metric_for_one_sample,
)
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def extract_binary(mask: int, length: int) -> tuple[int, ...]:
    return tuple(reversed(list(map(int, bin(mask)[2:].rjust(length, '0')))))


class SquidpyComputer(GenericJobComputer):
    """Calculate selected squidpy metrics."""

    def compute(self) -> None:
        if self.handle_excessive_sample_size('CELL_NUMBER_LIMIT_SQUIDPY', 750000):
            return
        args, arrays = self._prepare_parameters()
        if arrays.identifiers is None:
            self.handle_insert_value(None, allow_null=True)
        else:
            value = self._perform_computation(args, arrays)
            self.handle_insert_value(value, allow_null=True)

    def _prepare_parameters(
        self,
    ) -> tuple[tuple[str, tuple[PhenotypeCriteria, ...], float | None], CellDataArrays]:
        study = self.job.study
        feature_specification = str(self.job.feature_specification)
        method = retrieve_feature_derivation_method(self.connection, study, feature_specification)
        feature_class = cast(str, lookup_squidpy_feature_class(method))
        _, specifiers = SquidpyComputer.retrieve_specifiers(self.connection, study, feature_specification)
        phenotypes: tuple[PhenotypeCriteria, ...]
        if feature_class == 'co-occurrence':
            phenotypes = tuple(map(phenotype_str_to_phenotype, specifiers[0:2]))
            radius = float(specifiers[2])
        else:
            phenotypes = tuple(map(phenotype_str_to_phenotype, specifiers))
            radius = None
        arrays = self.get_cell_data_arrays()
        return ((feature_class, phenotypes, radius), arrays)

    def _perform_computation(
        self,
        args: tuple[str, tuple[PhenotypeCriteria, ...], float | None],
        arrays: CellDataArrays,
    ) -> float | None:
        feature_class, phenotypes, radius = args
        df = self._form_cells_dataframe(arrays)
        return compute_squidpy_metric_for_one_sample(df, phenotypes, feature_class, radius=radius)

    @staticmethod
    def _form_cells_dataframe(arrays: CellDataArrays) -> DataFrame:
        features = tuple(f.symbol for f in arrays.feature_names.names)
        rows = []
        zipped = zip(arrays.identifiers, arrays.phenotype, arrays.location.transpose())
        for identifier, phenotype, location in zipped:
            location_list = [location[0], location[1]]
            vector = list(extract_binary(phenotype, len(features)))
            row = tuple(vector + [identifier] + location_list)
            rows.append(row)
        columns = list(features) + ['histological_structure_id'] + ['pixel x', 'pixel y']
        df = DataFrame(rows, columns=columns)
        df.set_index('histological_structure_id', inplace=True)
        return df
