"""Queue of metrics to be computed as jobs."""

from smprofiler.ondemand.queue_query import select_active_jobs_query
from smprofiler.ondemand.queue_query import select_active_jobs_query_with_constraint
from smprofiler.ondemand.job_reference import ComputationJobReference
from psycopg import Cursor as PsycopgCursor
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class MetricsJobQueuePopper:
    @classmethod
    def pop_uncomputed(
        cls,
        preference: tuple[tuple[str, str], ...] | None=None,
        connection: DBConnection | None=None,
    ) -> ComputationJobReference | None:
        studies = cls._get_studies(connection=connection)
        number_studies = len(studies)
        studies_empty: set[str] = set([])
        while len(studies_empty) < number_studies:
            for study in set(studies).difference(studies_empty):
                with DBCursor(connection=connection, study=study) as cursor:
                    if preference != None and len(preference) > 0:
                        rows = cls._pop_uncomputed_with_constraint(study, preference, cursor)
                        if len(rows) == 0:
                            rows = cls._pop_uncomputed_without_constraint(cursor)
                    else:
                        rows = cls._pop_uncomputed_without_constraint(cursor)
                    if len(rows) == 1:
                        row = rows[0]
                        feature = int(row[0])
                        sample = str(row[1])
                        computation_start = row[2]
                        retries = int(row[3])
                        if computation_start is not None:
                            new_retries = retries + 1
                            logger.debug(f'Retrying due to assumed failure, iteration {new_retries}, ({feature}, {sample}).')
                        else:
                            new_retries = retries
                        cursor.execute('''
                            INSERT INTO quantitative_feature_value_queue
                                (feature, subject, computation_start, retries)
                            VALUES(
                                %s, %s, now(), %s
                            )
                            ''',
                            (feature, sample, new_retries)
                        )
                        return ComputationJobReference(feature, study, sample)
                    studies_empty.add(study)
                    continue
        return None

    @classmethod
    def _base_queue_pop_query(cls) -> str:
        return '''
        DELETE FROM
        quantitative_feature_value_queue q1
        USING (
            %s
            LIMIT 1
        ) q
        WHERE q1.feature=q.feature AND q1.subject=q.subject
        RETURNING q1.feature, q1.subject, q1.computation_start, q1.retries ;
        '''

    @classmethod
    def _pop_uncomputed_without_constraint(cls, cursor: PsycopgCursor) -> tuple:
        query = cls._base_queue_pop_query() % select_active_jobs_query()
        cursor.execute(query)
        rows = tuple(cursor.fetchall())
        return rows

    @classmethod
    def _pop_uncomputed_with_constraint(cls, study: str, constraint: tuple[tuple[str, str], ...], cursor) -> tuple:
        samples = tuple(map(lambda pair: pair[1], filter(lambda pair: pair[0] == study, constraint)))
        if len(samples) == 0:
            return cls._pop_uncomputed_without_constraint(cursor)
        query = cls._base_queue_pop_query() % select_active_jobs_query_with_constraint(samples)
        cursor.execute(query)
        rows = tuple(cursor.fetchall())
        return rows

    @classmethod
    def _get_studies(cls, connection: DBConnection | None=None) -> tuple[str, ...]:
        with DBCursor(connection=connection, study=None) as cursor:
            cursor.execute('SELECT study FROM study_lookup ;')
            return tuple(map(lambda row: row[0], cursor.fetchall()))
