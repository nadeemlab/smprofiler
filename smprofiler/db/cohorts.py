"""Convenience accessors and manipulators of cohort tables, identifiers, etc."""

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.exchange_data_formats.study import Cohort
from smprofiler.db.exchange_data_formats.study import CohortAssignment
from smprofiler.db.exchange_data_formats.study import SampleCohorts


def _replace_stratum_identifiers(rows: list, study: str, column_index: int) -> list:
    replacer = StratumIdentifierReplacer(study)
    return [[
            replacer.replace(entry) if i==column_index else entry
            for i, entry in enumerate(row)
        ]
        for row in rows
    ]


class StratumIdentifierReplacer:
    """Decrement stratum identifiers to study-scoped integers starting at 1."""
    decrement_amount: int

    def __init__(self, study: str):
        self.decrement_amount = self._get_decrement(study)

    def _get_decrement(self, study: str) -> int:
        with DBCursor(study=study) as cursor:
            cohort_identifiers = _get_cohort_identifiers_by_sample_original(cursor, study).values()
        return min((int(entry) for entry in cohort_identifiers)) - 1

    def replace(self, identifier: str) -> str:
        return str(int(identifier) - self.decrement_amount)


def get_sample_cohorts(cursor, study: str) -> SampleCohorts:
    cohorts = _get_cohorts_list(cursor, study)
    assignments = _get_cohort_assignments(cursor, study)
    return SampleCohorts(assignments=assignments, cohorts=cohorts)


def _get_cohorts_list(cursor, study: str) -> list[Cohort]:
    query = '''
    SELECT DISTINCT
        sst.stratum_identifier,
        sst.local_temporal_position_indicator,
        sst.subject_diagnosed_condition,
        sst.subject_diagnosed_result
    FROM sample_strata sst
    JOIN specimen_collection_process scp ON scp.specimen = sst.sample
    JOIN study_component sc ON sc.component_study=scp.study
    WHERE sc.primary_study=%s ;
    '''
    cursor.execute(query, (study,))
    sample_cohorts = cursor.fetchall()
    sample_cohorts_decremented = _replace_stratum_identifiers(sample_cohorts, study, column_index=0)
    sample_cohorts_obj = [
        Cohort(**dict(zip(['identifier', 'temporality', 'diagnosis', 'result'], row)))
        for row in sample_cohorts_decremented
    ]
    return sorted(sample_cohorts_obj, key=lambda cohort_obj: int(cohort_obj.identifier))


def _get_cohort_assignments(cursor, study: str) -> list[CohortAssignment]:
    query = '''
    SELECT scp.specimen
    FROM specimen_collection_process scp
    JOIN specimen_data_measurement_process sdmp
    ON scp.specimen=sdmp.specimen
    JOIN data_file df
    ON df.source_generation_process=sdmp.identifier
    JOIN study_component sc ON sc.component_study=scp.study
    WHERE sc.primary_study=%s
    ;
    '''
    cursor.execute(query, (study,))
    rows = cursor.fetchall()
    samples_with_datafile = list(map(lambda r: r[0], rows))
    cohort_identifiers = _get_cohort_identifiers_by_sample(cursor, study)
    available_samples = sorted(list(set(samples_with_datafile).intersection(cohort_identifiers.keys())))
    return [
        CohortAssignment(sample=sample, cohort=cohort_identifiers[sample])
        for sample in available_samples
    ]


def _get_cohort_identifiers_by_sample(cursor, study: str) -> dict[str, str]:
    cohort_identifiers = _get_cohort_identifiers_by_sample_original(cursor, study)
    replacer = StratumIdentifierReplacer(study)
    return {
        key: replacer.replace(value)
        for key, value in cohort_identifiers.items()
    }


def _get_cohort_identifiers_by_sample_original(cursor, study: str) -> dict[str, str]:
    query = '''
    SELECT sst.sample, sst.stratum_identifier
    FROM sample_strata sst
    JOIN specimen_collection_process scp ON scp.specimen = sst.sample
    JOIN study_component sc ON sc.component_study=scp.study
    WHERE sc.primary_study=%s
    ORDER BY sample ;
    '''
    cursor.execute(query, (study,))
    rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def get_cohort_identifiers(cursor, study: str) -> list[str]:
    return list(_get_cohort_identifiers_by_sample(cursor, study).values())
