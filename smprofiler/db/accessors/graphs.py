"""Convenience access of cg-gnn metrics."""

from pandas import (
    DataFrame,
    to_datetime,
)

from smprofiler.util import STRFTIME_FORMAT
from smprofiler.db.describe_features import get_feature_description
from smprofiler.db.database_connection import SimpleReadOnlyProvider

LATEST_ALIASES = {'latest', 'newest', 'recent', 'most recent'}


class GraphsAccess(SimpleReadOnlyProvider):
    """Access to graph features from database."""

    def _get_matching_feature_specification(
        self,
        study: str,
        plugin: str,
        datetime_of_run: str,
        plugin_version: str | None,
        cohort_stratifier: str | None,
    ) -> str:
        params = [plugin,]
        query = '''
            SELECT fs.identifier
            FROM feature_specification fs
                JOIN study_component sc
                    ON sc.component_study=fs.study
                JOIN (
                    SELECT feature_specification
                    FROM feature_specifier
                    WHERE ordinality='1' AND specifier=%s
                ) AS fsr1
                    ON fs.identifier = fsr1.feature_specification
                JOIN (
                    SELECT
                        feature_specification,
                        specifier
                    FROM feature_specifier
                    WHERE ordinality='2'
        '''
        if datetime_of_run not in LATEST_ALIASES:
            query += ' AND specifier=%s'
            params.append(to_datetime(datetime_of_run).strftime(STRFTIME_FORMAT))
        query += '''
                ) AS fsr2
                    ON fs.identifier = fsr2.feature_specification
        '''
        if plugin_version is not None:
            query += '''
                JOIN (
                    SELECT feature_specification
                    FROM feature_specifier
                    WHERE ordinality='3' AND specifier=%s
                ) AS fsr3
                    ON fs.identifier = fsr3.feature_specification
            '''
            params.append(plugin_version)
        if cohort_stratifier is not None:
            query += '''
                JOIN (
                    SELECT feature_specification
                    FROM feature_specifier
                    WHERE ordinality='4' AND specifier=%s
                ) AS fsr4
                    ON fs.identifier = fsr4.feature_specification
            '''
            params.append(cohort_stratifier)
        query += '''
                WHERE sc.primary_study=%s
                    AND fs.derivation_method=%s
                ORDER BY fsr2.specifier DESC
                LIMIT 1
            ;
        '''
        params.extend((study, get_feature_description("gnn importance score")))
        self.cursor.execute(query, params)
        feature_specification = self.cursor.fetchone()
        if feature_specification is None:
            raise ValueError('No matching feature specification found.')
        return feature_specification[0]

    def get_important_cells(
        self,
        study: str,
        plugin: str = 'cg-gnn',
        datetime_of_run: str = 'latest',
        plugin_version: str | None = None,
        cohort_stratifier: str | None = None,
        cell_limit: int = 100,
    ) -> set[int]:
        """Get the cell_limit most important cell IDs for each specimen in this study."""
        feature_specification = self._get_matching_feature_specification(
            study,
            plugin,
            datetime_of_run,
            plugin_version,
            cohort_stratifier,
        )
        query = '''
            SELECT
                qfv.subject,
                sdmp.specimen
            FROM quantitative_feature_value qfv
                JOIN histological_structure_identification hsi
                    ON hsi.histological_structure=qfv.subject
                JOIN data_file df
                    ON df.sha256_hash=hsi.data_source
                JOIN specimen_data_measurement_process sdmp
                    ON df.source_generation_process=sdmp.identifier
            WHERE qfv.feature=%s
            ORDER BY sdmp.specimen, qfv.value
            ;
        '''
        self.cursor.execute(query, (feature_specification,))
        rows = self.cursor.fetchall()
        df = DataFrame(rows, columns=['subject', 'sample'])
        truncated = df.groupby('sample').head(cell_limit)
        return set(map(int, truncated['subject']))
