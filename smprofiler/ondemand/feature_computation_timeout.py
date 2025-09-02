"""Helper timeout object."""
from os import environ as os_environ
from asyncio import get_event_loop as asyncio_get_event_loop
from time import sleep as time_sleep

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.database_connection import DBCursor
from smprofiler.ondemand.add_feature_value import add_feature_value
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def get_feature_timeout() -> int:
    DEFAULT_FEATURE_COMPUTATION_TIMEOUT_SECONDS = 600
    t = 'FEATURE_COMPUTATION_TIMEOUT_SECONDS'
    if t in os_environ:
        return int(os_environ[t])
    logger.warning(f'Set {t}. Using default: {DEFAULT_FEATURE_COMPUTATION_TIMEOUT_SECONDS}')
    return DEFAULT_FEATURE_COMPUTATION_TIMEOUT_SECONDS


class FeatureComputationTimeoutHandler:
    feature: str
    study: str

    def __init__(self, feature: str, study: str):
        self.feature = feature
        self.study = study

    def handle(self, timeout_seconds: int) -> None:
        if self._completed_size() < self._expected_size():
            logger.error(f'After {timeout_seconds} seconds feature {self.feature} ({self.study}) still not complete. Consider deleting it.')
            # self._delete_feature()
            self._insert_remaining_nulls()

    def _completed_size(self) -> int:
        with DBCursor(study=self.study) as cursor:
            query = 'SELECT COUNT(*) FROM quantitative_feature_value WHERE feature=%s ;'
            cursor.execute(query, (self.feature,))
            count = tuple(cursor.fetchall())[0][0]
        return count

    def _expected_size(self) -> int:
        with DBCursor(study=self.study) as cursor:
            query = 'SELECT COUNT(*) FROM specimen_data_measurement_process ;'
            cursor.execute(query)
            count = tuple(cursor.fetchall())[0][0]
        return count

    def _delete_feature(self) -> None:
        logger.error('Also deleting the feature, since the queue was empty; we assume the remaining jobs failed.')
        with DBCursor(study=self.study) as cursor:
            param = (self.feature,)
            cursor.execute('DELETE FROM quantitative_feature_value WHERE feature=%s ;', param)
            cursor.execute('DELETE FROM feature_specifier WHERE feature_specification=%s ;', param)
            cursor.execute('DELETE FROM feature_specification WHERE identifier=%s ;', param)

    def _insert_remaining_nulls(self) -> None:
        with DBCursor(study=self.study) as cursor:
            cursor.execute('''
                SELECT matched.specimen FROM
                (
                    SELECT sdmp.specimen, computedalready.subject
                    FROM specimen_data_measurement_process sdmp
                    LEFT JOIN
                        (
                            SELECT qfv.subject
                            FROM quantitative_feature_value qfv
                            WHERE qfv.feature=%s
                        ) as computedalready
                    ON computedalready.subject=sdmp.specimen
                ) as matched
                WHERE matched.subject IS NULL
                ;
            ''', (int(self.feature),))
            samples = tuple(map(lambda row: row[0], tuple(cursor.fetchall())))
            if len(samples) == 0:
                return
            logger.info(f'Inserting nulls for {self.feature}: {samples}')
            cursor.execute('''
                DELETE FROM
                quantitative_feature_value_queue
                WHERE feature=%s ;
            ''', (self.feature,))
            for sample in samples:
                add_feature_value(self.feature, sample, None, cursor)


def do_in_background(f):
    def wrapped(*args, **kwargs):
        return asyncio_get_event_loop().run_in_executor(None, f, *args, **kwargs)
    return wrapped


@do_in_background
def feature_computation_timeout_handler(feature: str, study: str, timeout: int):
    if 'SMProfiler_TESTING_MODE' in os_environ:
        return
    elapsed = 0
    minute = 60
    increment = 1 * minute
    while elapsed < timeout:
        time_sleep(increment)
        elapsed += increment
    handler = FeatureComputationTimeoutHandler(feature, study)
    handler.handle(timeout)
