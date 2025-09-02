from abc import ABC
from abc import abstractmethod
from math import isnan
from math import isinf

from smprofiler.apiserver.request_scheduling.metrics_job_queue_insertion import MetricsJobQueuePusher
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.ondemand.relevant_specimens import relevant_specimens_query
from smprofiler.db.exchange_data_formats.metrics import \
    UnivariateMetricsComputationResult
from smprofiler.workflow.common.export_features import \
    ADIFeatureSpecificationUploader
from smprofiler.ondemand.providers.study_component_extraction import ComponentGetter
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def _json_compliant_float(value: str) -> float | None:
    if value is not None:
        floated = float(value)
        if not (isnan(floated) or isinf(floated)):
            return floated
    return None

def retrieve_feature_derivation_method(connection: DBConnection, study: str, feature_specification: str) -> str:
    with DBCursor(connection=connection, study=study) as cursor:
        cursor.execute('''
            SELECT derivation_method FROM feature_specification
            WHERE identifier=%s ;
            ''',
            (feature_specification,),
        )
        rows = tuple(cursor.fetchall())
    return rows[0][0]


class GenericComputationScheduler(ABC):
    @classmethod
    def get_metrics_or_schedule(
        cls,
        connection: DBConnection,
        study: str,
        **kwargs,
    ) -> tuple[UnivariateMetricsComputationResult, str]:
        """Get requested metrics, computed up to now."""
        with DBCursor(connection=connection, study=study) as cursor:
            get = ADIFeatureSpecificationUploader.get_data_analysis_study
            measurement_study_name = ComponentGetter.get_study_components(cursor, study).measurement
            data_analysis_study = get(measurement_study_name, cursor)
        get_or_create = cls.get_or_create_feature_specification
        feature_specification, is_new = get_or_create(connection, study, data_analysis_study, **kwargs)
        all_jobs_complete = cls._all_jobs_complete(connection, study, feature_specification)
        if is_new and all_jobs_complete:
            fs = feature_specification
            logger.warning(f'Newly created feature somehow has all jobs complete already ({fs}).')
        if all_jobs_complete:
            return (cls._query_for_computed_feature_values(
                connection,
                study,
                feature_specification,
                still_pending=False,
            ), feature_specification)
        if is_new:
            MetricsJobQueuePusher.schedule_feature_computation(connection, study, int(feature_specification))
        return (
            cls._query_for_computed_feature_values(
                connection,
                study,
                feature_specification,
                still_pending=True,
            ),
            feature_specification,
        )

    @classmethod
    def _all_jobs_complete(cls, connection: DBConnection, study: str, feature_specification: str) -> bool:
        with DBCursor(connection=connection, study=study) as cursor:
            query = 'SELECT COUNT(*) FROM quantitative_feature_value WHERE feature=%s ;'
            cursor.execute(query, (feature_specification,))
            count = tuple(cursor.fetchall())[0][0]
        expected = cls._get_expected_number_samples(connection, study, feature_specification)
        if count > expected:
            message = f'Feature {feature_specification} has too many values, {count} / {expected}.'
            logger.warning(message)
        return count == expected

    @classmethod
    @abstractmethod
    def get_or_create_feature_specification(
        cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        **kwargs,
    ) -> tuple[str, bool]:
        """Return feature specification, creating one if necessary."""
        raise NotImplementedError("For subclasses to implement.")

    @staticmethod
    def create_feature_specification(
        connection: DBConnection,
        study: str,
        specifiers: tuple[str, ...],
        data_analysis_study: str,
        method: str,
        appendix: str | None = None,
    ) -> str:
        # connection.get_connection()._set_autocommit(True)
        with DBCursor(connection=connection, study=study) as cursor:
            feature_specification = ADIFeatureSpecificationUploader.add_new_feature(
                specifiers, method, data_analysis_study, cursor, appendix=appendix,
            )
        return feature_specification

    @classmethod
    def _get_expected_number_samples(cls, connection: DBConnection, study: str, feature_specification: str) -> int:
        return len(cls._get_expected_samples(connection, study, feature_specification))

    @classmethod
    def _get_expected_samples(cls, connection: DBConnection, study: str, feature_specification: str) -> tuple[str, ...]:
        with DBCursor(connection=connection, study=study) as cursor:
            query = relevant_specimens_query() % f"'{feature_specification}'"
            cursor.execute(query)
            return tuple(map(lambda row: row[0], cursor.fetchall()))

    @classmethod
    def _query_for_computed_feature_values(
        cls,
        connection: DBConnection,
        study: str,
        feature_specification: str,
        still_pending: bool = False
    ) -> UnivariateMetricsComputationResult:
        with DBCursor(connection=connection, study=study) as cursor:
            cursor.execute('''
                SELECT qfv.subject, qfv.value
                FROM quantitative_feature_value qfv
                WHERE qfv.feature=%s
                ''',
                (feature_specification,),
            )
            rows = tuple(cursor.fetchall())
            metrics = {
                str(row[0]): _json_compliant_float(row[1])
                for row in rows
            }
            sorted_metrics = {key: metrics[key] for key in sorted(list(metrics.keys()))}
        return UnivariateMetricsComputationResult(
            values = sorted_metrics,
            is_pending = still_pending,
        )
