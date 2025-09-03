"""Convenience reporter of the run configuration for a given workflow, before it actually runs. For
debugging and archival purposes.
"""

from typing import cast
from os.path import getsize
import datetime
import socket

import pandas as pd

from smprofiler.workflow.tabular_import.tabular_dataset_design \
    import TabularCellMetadataDesign
from smprofiler.standalone_utilities.configuration_settings import get_version
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class RunConfigurationReporter:
    """Convenience reporter of run configuration."""

    def __init__(
        self,
        workflow: str = '',
        file_manifest_file: str = '',
        data_files: dict[str, str | None] | None=None,
    ):
        data_files = cast(dict[str, str | None], data_files)
        logger.info('Machine host: %s', socket.gethostname())
        logger.info('Version: SMProfiler v%s', get_version())
        logger.info('Workflow: "%s"', workflow)

        file_metadata = pd.read_csv(file_manifest_file, sep='\t', keep_default_na=False)
        project_handle = sorted(list(set(file_metadata['Project ID']).difference([''])))[0]
        if project_handle != '':
            logger.info('Dataset/project: "%s"', project_handle)
            current = datetime.datetime.now()
            logger.info('Run date year: %s', current.date().strftime("%Y"))

        sizes = self.retrieve_cell_manifest_sizes(file_manifest_file)
        logger.info('Number of cell manifest files: %s', len(sizes))
        logger.info('Total cell manifest file size: %s MB',
                    self.format_mb(sum(sizes)))
        logger.info('Smallest cell manifest: %s MB',
                    self.format_mb(min(sizes)))
        logger.info('Largest cell manifest: %s MB', self.format_mb(max(sizes)))

        if data_files['samples']:
            samples = pd.read_csv(data_files['samples'], sep='\t', keep_default_na=False, dtype=str)
        else:
            sample_ids = self.retrieve_cell_manifest_sample_identifiers(file_manifest_file)
            samples = pd.DataFrame({
                'Sample ID': sample_ids,
                'Outcome': ['Unknown outcome assignment' for i in sample_ids],
            })[['Sample ID', 'Outcome']]
        labels = sorted(list(set(samples[samples.columns[1]])))

        channels_df = pd.read_csv(cast(str, data_files['channels']), keep_default_na=False)
        phenotypes = pd.read_csv(cast(str, data_files['phenotypes']), keep_default_na=False)
        channels = sorted(list(set(channels_df['Name'])))

        logger.info('Number of outcome labels: %s', len(labels))
        logger.info('Number of channels: %s', channels_df.shape[0])
        logger.info('Number of phenotypes considered: %s', phenotypes.shape[0])
        logger.info('Channels: %s', '; '.join(map(str, channels)))

    def get_frequencies(self, samples):
        column = samples[samples.columns[1]]
        labels = sorted(list(set(column)))
        return {label: sum(1 for value in column if value == label) for label in labels}

    def format_mb(self, number_bytes):
        return int(10 * number_bytes / 1000000) / 10

    def retrieve_cell_manifest_sizes(self, file_manifest_file):
        validate = TabularCellMetadataDesign.validate_cell_manifest_descriptor
        return [
            getsize(row['File name'])
            for _, row in pd.read_csv(file_manifest_file, sep='\t').iterrows()
            if validate(row['Data type'])
        ]

    def retrieve_cell_manifest_sample_identifiers(self, file_manifest_file):
        validate = TabularCellMetadataDesign.validate_cell_manifest_descriptor
        return [
            row['Sample ID']
            for _, row in pd.read_csv(file_manifest_file, sep='\t').iterrows()
            if validate(row['Data type'])
        ]
