
from typing import cast

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.ondemand.phenotype_str import phenotype_to_phenotype_str
from smprofiler.db.describe_features import get_feature_description
from smprofiler.apiserver.request_scheduling.computation_scheduler import GenericComputationScheduler
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class ProximityScheduler(GenericComputationScheduler):
    @classmethod
    def get_or_create_feature_specification(
        cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        phenotype1: PhenotypeCriteria | None = None,
        phenotype2: PhenotypeCriteria | None = None,
        radius: float | None = None,
        **kwargs,
    ) -> tuple[str, bool]:
        phenotype1 = cast(PhenotypeCriteria, phenotype1)
        phenotype2 = cast(PhenotypeCriteria, phenotype2)
        radius = cast(float, radius)
        specifiers_arguments = (
            data_analysis_study,
            phenotype_to_phenotype_str(phenotype1),
            phenotype_to_phenotype_str(phenotype2),
            str(radius),
        )
        specification = cls._get_feature_specification(connection, study, *specifiers_arguments)
        if specification is not None:
            return (specification, False)
        message = 'Creating feature with specifiers: (%s) %s, %s, %s'
        logger.debug(message, *specifiers_arguments)
        return (cls._create_feature_specification(connection, study, *specifiers_arguments), True)

    @classmethod
    def _get_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        phenotype1_str: str,
        phenotype2_str: str,
        radius_str: str,
    ) -> str | None:
        args = (
            data_analysis_study,
            phenotype1_str,
            phenotype2_str,
            radius_str,
            get_feature_description('proximity'),
        )
        with DBCursor(connection=connection, study=study) as cursor:
            cursor.execute('''
            SELECT
                fsn.identifier,
                fs.specifier
            FROM feature_specification fsn
            JOIN feature_specifier fs ON fs.feature_specification=fsn.identifier
            JOIN study_component sc ON sc.component_study=fsn.study
            JOIN study_component sc2 ON sc2.primary_study=sc.primary_study
            WHERE sc2.component_study=%s AND
                  (   (fs.specifier=%s AND fs.ordinality='1')
                   OR (fs.specifier=%s AND fs.ordinality='2')
                   OR (fs.specifier=%s AND fs.ordinality='3') ) AND
                  fsn.derivation_method=%s
            ;
            ''', args)
            rows = cursor.fetchall()
        feature_specifications: dict[str, list[str]] = {row[0]: [] for row in rows}
        for row in rows:
            feature_specifications[row[0]].append(row[1])
        for key, specifiers in feature_specifications.items():
            if len(specifiers) == 3:
                return key
        return None

    @classmethod
    def _create_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        phenotype1: str,
        phenotype2: str,
        radius: str,
    ) -> str:
        specifiers = (phenotype1, phenotype2, str(radius))
        method = get_feature_description('proximity')
        return cls.create_feature_specification(connection, study, specifiers, data_analysis_study, method)
