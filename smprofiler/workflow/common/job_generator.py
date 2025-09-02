"""Convenience functions for job generation."""

from smprofiler.db.database_connection import DBCursor

def retrieve_sample_identifiers_from_db(study_name, database_config_file):
    with DBCursor(database_config_file=database_config_file, study=study_name) as cursor:
        query = '''
        SELECT scp.specimen
        FROM specimen_collection_process scp
        JOIN study_component sc ON sc.component_study=scp.study
        WHERE sc.primary_study=%s
        AND EXISTS (SELECT sdmp.identifier FROM specimen_data_measurement_process sdmp WHERE sdmp.specimen=scp.specimen)
        ORDER BY scp.specimen
        ;            '''
        cursor.execute(query, (study_name,))
        rows = cursor.fetchall()
    return [row[0] for row in rows]
