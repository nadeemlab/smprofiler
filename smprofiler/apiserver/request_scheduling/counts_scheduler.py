
from typing import cast

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.ondemand.relevant_specimens import retrieve_cells_selected
from smprofiler.ondemand.phenotype_str import phenotype_to_phenotype_str
from smprofiler.db.describe_features import get_feature_description
from smprofiler.apiserver.request_scheduling.computation_scheduler import GenericComputationScheduler
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class CountsScheduler(GenericComputationScheduler):
    @classmethod
    def get_or_create_feature_specification(
        cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        phenotype: PhenotypeCriteria | None = None,
        cells_selected: tuple[int, ...] = (),
        **kwargs,
    ) -> tuple[str, bool]:
        if phenotype is None:
            phenotype = PhenotypeCriteria(positive_markers=(), negative_markers=())
        else:
            phenotype = cast(PhenotypeCriteria, phenotype)
        specifiers_arguments = (
            data_analysis_study,
            phenotype,
            cells_selected,
        )
        specification = cls._get_feature_specification(connection, study, *specifiers_arguments)
        if specification is not None:
            _cells_selected = retrieve_cells_selected(connection, study, specification)
            if set(cells_selected) == set(_cells_selected):
                return (specification, False)
        short = str(cells_selected[0:min(len(cells_selected), 5)]) + ' ...'
        addend = f' (and cell set {short}, {len(cells_selected)} cells)' if cells_selected != () else ''
        message = 'Creating feature with specifiers: %s' + addend
        logger.debug(message, phenotype)
        specifiers_arguments_str = (
            data_analysis_study,
            phenotype_to_phenotype_str(phenotype),
        )
        specification = cls._create_feature_specification(connection, study, *specifiers_arguments_str, appendix=str(cells_selected))
        cls._append_cell_set(connection, study, specification, cells_selected) # Check that this does not need to be rolled into the transaction in the above line
        return (specification, True)

    @classmethod
    def _append_cell_set(
        cls, connection: DBConnection, study: str, specification: str, cells_selected: tuple[int, ...],
    ) -> None:
        with DBCursor(connection=connection, study=study) as cursor:
            copy_command = 'COPY cell_set_cache (feature, histological_structure) FROM STDIN'
            with cursor.copy(copy_command) as copy:
                for cell in cells_selected:
                    copy.write_row((specification, str(cell)))

    @classmethod
    def _check_cell_set(
        cls, connection: DBConnection, study: str, feature: str, _cells_selected: tuple[int, ...],
    ) -> bool:
        with DBCursor(connection=connection, study=study) as cursor:
            query = '''
            SELECT histological_structure
            FROM cell_set_cache
            WHERE feature=%s ;
            '''
            cursor.execute(query, (feature,))
            rows = tuple(cursor.fetchall())
        cells = tuple(sorted(list(map(lambda row: int(row[0]), rows))))
        cells_selected = tuple(sorted(list(_cells_selected)))
        if len(cells) == 0 or len(cells_selected) == 0:
            return len(cells) == len(cells_selected)
        condition = cells == cells_selected
        return condition

    @classmethod
    def _get_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        phenotype: PhenotypeCriteria,
        cells_selected: tuple[int, ...],
    ) -> str | None:
        cells = f'{cells_selected[0:min(5, len(cells_selected))]} ... ({len(cells_selected)})'
        feature_description = get_feature_description('population fractions')
        args = (
            data_analysis_study,
            phenotype_to_phenotype_str(phenotype),
            feature_description,
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
                  ( fs.specifier=%s AND fs.ordinality='1') AND
                  fsn.derivation_method=%s
            ;
            ''', args)
            rows = tuple(cursor.fetchall())
        feature_specifications: dict[str, list[str]] = {row[0]: [] for row in rows}
        matches_list: list[str] = []
        for row in rows:
            feature_specifications[row[0]].append(row[1])
        for key, specifiers in feature_specifications.items():
            if len(specifiers) == 1:
                matches_list.append(key)
        matches = tuple(filter(
            lambda feature: cls._check_cell_set(connection, study, feature, cells_selected),
            matches_list,
        ))
        if len(matches) == 0:
            return None
        if len(matches) > 1:
            text = 'Multiple features match the selected specification'
            message = f'{text}: {matches} {phenotype} {cells}'
            logger.warning(message)
        return matches[0]

    @classmethod
    def _create_feature_specification(cls,
        connection: DBConnection,
        study: str,
        data_analysis_study: str,
        phenotype: str,
        appendix: str | None=None,
    ) -> str:
        specifiers = (phenotype,)
        method = get_feature_description('population fractions')
        return cls.create_feature_specification(connection, study, specifiers, data_analysis_study, method, appendix=appendix)
