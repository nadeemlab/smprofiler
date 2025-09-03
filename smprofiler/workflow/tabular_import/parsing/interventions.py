"""Source file parsing for treatment/intervention-related data."""
import pandas as pd

from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class InterventionsParser(SourceToADIParser):
    """Source file parsing for treatment/intervention event metadata."""
    def parse(self, connection, interventions_file):
        cursor = connection.cursor()

        logger.debug('Considering %s', interventions_file)
        interventions = pd.read_csv(interventions_file, sep='\t', na_filter=False, dtype=str)
        logger.info('Saving %s intervention records.', interventions.shape[0])
        for _, row in interventions.iterrows():
            intervention_record = (
                row['Subject of intervention'],
                row['Intervention'],
                row['Date of intervention'],
            )
            cursor.execute(self.generate_basic_insert_query('intervention'), intervention_record)
        connection.commit()
        cursor.close()
