
import re
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.sqlite_builder import SQLiteBuilder

def _normalize(name):
    name = re.sub(' collection: .*$', '', name)
    return re.sub(r'[ \-]', '_', name).lower()

def test_sqlite_dump():
    database_config_file = '../db/.smprofiler_db.config.container'
    connection = DBConnection(database_config_file=database_config_file)
    connection.__enter__()
    with DBCursor(connection=connection, study=None) as cursor:
        cursor.execute('SELECT study FROM default_study_lookup.study_lookup;')
        studies = tuple(map(lambda row: row[0], tuple(cursor.fetchall())))

    builder = SQLiteBuilder(connection, no_feature_values=True, no_feature_specifications=True)
    for study in studies:
        dump = builder.get_dump(study)
        with open(f'dump_{_normalize(study)}_metadata_only.db', 'wb') as file:
            file.write(dump)

    builder = SQLiteBuilder(connection, no_feature_values=True)
    for study in studies:
        dump = builder.get_dump(study)
        with open(f'dump_{_normalize(study)}.db', 'wb') as file:
            file.write(dump)

    builder = SQLiteBuilder(connection)
    for study in studies:
        dump = builder.get_dump(study)
        with open(f'dump_{_normalize(study)}_with_feature_values.db', 'wb') as file:
            file.write(dump)

    connection.__exit__(None, None, None)

if __name__=='__main__':
    test_sqlite_dump()
