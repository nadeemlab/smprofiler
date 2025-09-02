"""Source file parsing for sample-level metadata."""
import pandas as pd

from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.workflow.tabular_import.parsing.value_extraction import \
    get_unique_value
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class SamplesParser(SourceToADIParser):
    """Source file parsing for sample-level metadata."""

    def parse(self, connection, samples_file, study_name) -> None:
        """Retrieve the samples information and parse records for:
        - specimen collection study
        - specimen collection process
        - histology assessment process
        """
        samples = pd.read_csv(samples_file, sep='\t', dtype=str)

        collection_study = SourceToADIParser.get_collection_study_name(study_name)
        extraction_method = get_unique_value(samples, 'Extraction method')
        preservation_method = get_unique_value(samples, 'Preservation method')
        storage_location = get_unique_value(samples, 'Storage location')

        cursor = connection.cursor()
        cursor.execute(
            self.generate_basic_insert_query('specimen_collection_study'),
            (collection_study, extraction_method,
             preservation_method, storage_location, '', ''),
        )

        for _, sample in samples.iterrows():
            record = self._create_specimen_collection_process_record(
                sample,
                collection_study,
            )
            cursor.execute(self.generate_basic_insert_query('specimen_collection_process'), record)

        for _, sample in samples.iterrows():
            if sample['Assay'] == '' or sample['Assessment'] == '':
                continue
            record = self._create_histology_assessment_process_record(sample)
            cursor.execute(self.generate_basic_insert_query('histology_assessment_process'), record)

        logger.info('Parsed records for %s specimens.', samples.shape[0])
        connection.commit()
        cursor.close()

    def _create_specimen_collection_process_record(self, sample, collection_study):
        return (
            sample['Sample ID'],
            sample['Source subject'],
            sample['Source site'],
            sample['Source subject age at specimen collection'],
            sample['Extraction date'],
            collection_study,
        )

    def _create_histology_assessment_process_record(self, sample):
        return (
            sample['Sample ID'],
            sample['Assay'],
            sample['Assessment'],
            '',
            '',
        )
