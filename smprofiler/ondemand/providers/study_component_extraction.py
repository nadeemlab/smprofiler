import re

from psycopg import Cursor as PsycopgCursor
from smprofiler.db.exchange_data_formats.study import StudyComponents
from smprofiler.workflow.common.export_features import ADIFeatureSpecificationUploader

class ComponentGetter:
    @classmethod
    def get_study_components(cls, cursor: PsycopgCursor, study: str) -> StudyComponents:
        substudy_tables = {
            'collection': 'specimen_collection_study',
            'measurement': 'specimen_measurement_study',
            'analysis': 'data_analysis_study',
        }
        substudies = {}
        for key, tablename in substudy_tables.items():
            cursor.execute(f'''
            SELECT ss.name FROM {tablename} ss
            JOIN study_component sc ON sc.component_study=ss.name
            WHERE sc.primary_study=%s
            ;
            ''', (study,))
            name = [
                row[0] for row in cursor.fetchall()
                if not cls._is_secondary_substudy(row[0])
            ][0]
            substudies[key] = name
        return StudyComponents(**substudies)

    @classmethod
    def _is_secondary_substudy(cls, substudy: str) -> bool:
        is_fractions = bool(re.search('phenotype fractions', substudy))
        is_proximity_calculation = bool(re.search('proximity calculation', substudy))
        descriptor = ADIFeatureSpecificationUploader.ondemand_descriptor()
        is_ondemand_calculation = bool(re.search(descriptor, substudy))
        return is_fractions or is_proximity_calculation or is_ondemand_calculation
