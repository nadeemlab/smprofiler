"""Source file parsing for diagnosis/outcome data."""
import pandas as pd

from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class DiagnosisParser(SourceToADIParser):
    """Source file parsing for outcome/diagnosis metadata."""

    def parse(self, connection, diagnosis_file):
        cursor = connection.cursor()

        logger.debug('Considering %s', diagnosis_file)
        diagnoses = pd.read_csv(diagnosis_file, sep='\t', na_filter=False, dtype=str)
        logger.info('Saving %s diagnosis records.', diagnoses.shape[0])
        for _, row in diagnoses.iterrows():
            diagnosis_record = (
                row['Subject of diagnosis'],
                row['Diagnosed condition'],
                row['Diagnosis'],
                '',
                row['Date of diagnosis'],
                row['Last date of considered evidence'],
            )
            cursor.execute(self.generate_basic_insert_query('diagnosis'), diagnosis_record)
        connection.commit()
        cursor.close()
