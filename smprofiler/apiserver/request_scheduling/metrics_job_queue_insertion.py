
from psycopg import Cursor as PsycopgCursor

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.ondemand.relevant_specimens import relevant_specimens_query
from smprofiler.ondemand.feature_computation_timeout import feature_computation_timeout_handler
from smprofiler.ondemand.feature_computation_timeout import get_feature_timeout
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class MetricsJobQueuePusher:
    @classmethod
    def schedule_feature_computation(cls, connection: DBConnection, study: str, feature_specification: int) -> None:
        with DBCursor(connection=connection, database_config_file=None, study=study) as cursor:
            cls._insert_jobs(cursor, feature_specification)
        connection.get_connection().commit()
        timeout = get_feature_timeout()
        feature_computation_timeout_handler(str(feature_specification), study, timeout)
        cls._broadcast_queue_activity()

    @classmethod
    def _broadcast_queue_activity(cls) -> None:
        logger.debug('Notifying queue activity channel that there are new items.')
        with DBConnection() as connection:
            connection.execute('NOTIFY new_items_in_queue ;')

    @classmethod
    def _insert_jobs(cls, cursor: PsycopgCursor, feature_specification: int) -> None:
        query = '''
        INSERT INTO quantitative_feature_value_queue
            (feature, subject, computation_start, retries)
        SELECT
            %s, sq.specimen, NULL, 0
        FROM ( %s ) sq
        ON CONFLICT DO NOTHING ;
        ''' % (
            f"'{feature_specification}'",
            relevant_specimens_query() % f"'{feature_specification}'",
        )
        cursor.execute(query)
