"""
Generate the list of jobs for tabular import.
"""
from os.path import join
from os.path import exists
from typing import cast

from pandas import read_csv
from pandas import DataFrame

from smprofiler.workflow.component_interfaces.job_generator import JobGenerator
from smprofiler.workflow.tabular_import.tabular_dataset_design\
    import TabularCellMetadataDesign
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class TabularImportJobGenerator(JobGenerator):
    """Generate the list of jobs for tabular import."""

    def __init__(self,
        input_path: str | None = None,
        file_manifest_file: str | None = None,
        dataset_design_class = TabularCellMetadataDesign,
    ):
        self.input_path = cast(str, input_path)
        self.dataset_design_class = dataset_design_class
        file_manifest_file = cast(str, file_manifest_file)
        if not exists(file_manifest_file):
            raise FileNotFoundError(file_manifest_file)
        self.file_metadata = read_csv(file_manifest_file, sep='\t')

    def retrieve_file_records(self, condition=lambda x: True):
        return [record for i, record in self.file_metadata.iterrows() if condition(record)]

    def write_job_specification_table(self, job_specification_table_filename):
        """Prepares the job specification table for the orchestrator."""
        validate = self.dataset_design_class.validate_cell_manifest_descriptor
        records = self.retrieve_file_records(condition=lambda record: validate(record['Data type']))

        rows = [
            {
                'input_file_identifier' : record['File ID'],
                'input_filename': join(self.input_path, record['File name']),
            } for record in records
        ]
        df = DataFrame(rows)
        columns = map(str, df.columns)  # type: ignore
        df = df[sorted(columns)]
        df.to_csv(job_specification_table_filename, index=False, header=True)
