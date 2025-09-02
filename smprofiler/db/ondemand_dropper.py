"""Drop ondemand-computed feature values, specifications, etc."""

from typing import cast
import re

from psycopg import Cursor as PsycopgCursor

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class OnDemandComputationsDropper:
    """Drop ondemand-computed feature values, specifications, etc."""

    @staticmethod
    def drop(cursor: PsycopgCursor):
        specifications = cast(list[str], OnDemandComputationsDropper.get_droppable(cursor))
        OnDemandComputationsDropper.drop_features(cursor, specifications)

    @staticmethod
    def get_droppable(cursor: PsycopgCursor) -> list[str] | None:
        cursor.execute('SELECT DISTINCT study FROM feature_specification;')
        studies = [row[0] for row in cursor.fetchall()]
        studies = [s for s in studies if re.search(r' ondemand computed features$', s)]
        specifications: list[str] = []
        for study in studies:
            query = 'SELECT identifier FROM feature_specification WHERE study=%s ;'
            cursor.execute(query, (study,))
            _specifications = [row[0] for row in cursor.fetchall()]
            specifications = specifications + _specifications
        return specifications

    @staticmethod
    def drop_features(cursor: PsycopgCursor, specifications: list[str], just_features: bool=False, verbose: bool=True):
        for specification in specifications:
            queries = [
                'DELETE FROM quantitative_feature_value WHERE feature=%s ;',
                'DELETE FROM quantitative_feature_value_queue WHERE feature=%s ;',
                'DELETE FROM feature_specifier WHERE feature_specification=%s ;',
                'DELETE FROM feature_specification WHERE identifier=%s ;',
            ]
            for query in queries:
                if verbose:
                    logger.debug(query, specification)
                cursor.execute(query, (specification,))
        if just_features:
            return
        cursor.execute('DELETE FROM cell_set_cache ;')
        cursor.execute('DELETE FROM quantitative_feature_value_queue ;')
        cursor.execute('DELETE FROM feature_hash ;')
