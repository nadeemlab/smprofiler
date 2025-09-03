
from typing import cast
from itertools import chain

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.ondemand.phenotype_str import phenotype_to_phenotype_str
from smprofiler.db.describe_features import get_feature_description
from smprofiler.apiserver.request_scheduling.computation_scheduler import GenericComputationScheduler
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class SquidpyScheduler(GenericComputationScheduler):
    @classmethod
    def get_or_create_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        feature_class: str | None = None,
        phenotypes: list[PhenotypeCriteria] | None = None,
        radius: float | None = None,
        **kwargs,
    ) -> tuple[str, bool]:
        """Create and return the identifier of a feature specification defined by the specifiers,
        if it does not exist. If it already exists, return the already-existing specification's
        identifier.
        """
        feature_class = cast(str, feature_class)
        phenotypes = cast(list[PhenotypeCriteria], phenotypes)
        phenotypes_strs: list[str] = [
            phenotype_to_phenotype_str(phenotype) for phenotype in phenotypes
        ]
        specification = cls._get_feature_specification(
            connection,
            study,
            data_analysis_study,
            feature_class,
            phenotypes_strs,
            radius=radius,
        )
        if specification is not None:
            return (specification, False)
        if radius is not None:
            message = 'Creating feature with specifiers: (%s) %s, %s'
            logger.debug(message, data_analysis_study, str(phenotypes_strs), radius)
        else:
            message = 'Creating feature with specifiers: (%s) %s'
            logger.debug(message, data_analysis_study, str(phenotypes_strs))
        return (cls._create_feature_specification(
            connection,
            study,
            data_analysis_study,
            feature_class,
            phenotypes_strs,
            radius=radius,
        ), True)

    @classmethod
    def _get_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        feature_class:str,
        phenotypes_strs: list[str],
        radius: float | None = None,
    ) -> str | None:
        specifiers = phenotypes_strs
        if feature_class == 'co-occurrence':
            specifiers = specifiers + [str(radius)]
        query = cls._form_query_for_feature_specifiers(len(specifiers))
        method = cast(str, get_feature_description(feature_class))
        variable_portion_args = list(chain(*[
            [specifier, str(i+1)] for i, specifier in enumerate(specifiers)
        ]))
        with DBCursor(connection=connection, study=study) as cursor:
            cursor.execute(query, tuple([data_analysis_study] + variable_portion_args + [method]))
            rows = cursor.fetchall()
        feature_specifications: dict[str, list[str]] = {row[0]: [] for row in rows}
        for row in rows:
            feature_specifications[row[0]].append(row[1])
        for key, _specifiers in feature_specifications.items():
            if len(_specifiers) == len(specifiers):
                return key
        return None

    @classmethod
    def _form_query_for_feature_specifiers(cls, number_specifiers: int) -> str:
        query_header = '''
        SELECT
            fsn.identifier,
            fs.specifier
        FROM feature_specification fsn
            JOIN feature_specifier fs
                ON fs.feature_specification=fsn.identifier
            JOIN study_component sc
                ON sc.component_study=fsn.study
            JOIN study_component sc2
                ON sc2.primary_study=sc.primary_study
        WHERE sc2.component_study=%s AND
            ( '''
        variable_portion_template = ' (fs.specifier=%s AND fs.ordinality=%s) '
        variable_portion = ' OR '.join([
            variable_portion_template
            for i in range(number_specifiers)
        ])
        query_footer = ''') AND
            fsn.derivation_method=%s
        ;
        '''
        return query_header + variable_portion + query_footer

    @classmethod
    def _create_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        feature_class: str,
        phenotypes: list[str],
        radius: float | None = None,
    ) -> str:
        if feature_class == 'co-occurrence':
            specifiers = tuple(phenotypes[0:2] + [str(radius)])
        else:
            specifiers = tuple(phenotypes)
        method = cast(str, get_feature_description(feature_class))
        return cls.create_feature_specification(connection, study, specifiers, data_analysis_study, method)
