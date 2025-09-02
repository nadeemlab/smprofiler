
from psycopg import Cursor as PsycopgCursor

def add_feature_value(feature_specification, subject, value, cursor: PsycopgCursor):
    cursor.execute(
        '''
        INSERT INTO quantitative_feature_value (feature, subject, value) VALUES (%s, %s, %s) ;
        ''',
        (feature_specification, subject, value),
    )
