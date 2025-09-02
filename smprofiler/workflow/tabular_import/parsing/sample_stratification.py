"""Source file parsing regarding sample-level cohort identification."""
import re
from typing import Callable
from typing import Any

import pandas as pd

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class SampleStratificationCreator:
    """Create a simplified sample stratification (cohort definition) for the samples across all
    studies.
    """

    insert_assignment = '''
    INSERT INTO sample_strata
    ( stratum_identifier,
    sample,
    local_temporal_position_indicator,
    subject_diagnosed_condition,
    subject_diagnosed_result )
    VALUES ( %s, %s, %s, %s, %s )
    ;
    '''

    @staticmethod
    def create_sample_stratification(connection):
        cursor = connection.cursor()
        text = 'Creating sample (specimen) stratification based on diagnoses and/or interventions.'
        logger.info(text)

        specimens = SampleStratificationCreator.get_unassigned_specimen_ids(cursor)
        identifiers = {}
        strata_count = SampleStratificationCreator.get_last_assigned_stratum_identifier(cursor)
        assignment_count = 0
        for specimen in specimens:
            key = tuple(SampleStratificationCreator.get_interventional_diagnosis(specimen, cursor))
            (
                local_temporal_position_indicator,
                subject_diagnosed_condition,
                subject_diagnosed_result,
            ) = key
            if key == ('', '', ''):
                continue
            if key not in identifiers:
                strata_count = strata_count + 1
                identifiers[key] = strata_count
            record = (
                str(identifiers[key]),
                specimen,
                local_temporal_position_indicator,
                subject_diagnosed_condition,
                subject_diagnosed_result,
            )
            cursor.execute(SampleStratificationCreator.insert_assignment, record)
            assignment_count = assignment_count + 1

        for specimen in specimens:
            key = tuple(
                SampleStratificationCreator.get_interventional_diagnosis(specimen, cursor))
            (local_temporal_position_indicator,
             subject_diagnosed_condition,
             subject_diagnosed_result) = key
            if key != ('', '', ''):
                continue
            if key not in identifiers:
                strata_count = strata_count + 1
                identifiers[key] = strata_count
            record = (
                str(identifiers[key]),
                specimen,
                local_temporal_position_indicator,
                subject_diagnosed_condition,
                subject_diagnosed_result,
            )
            cursor.execute(SampleStratificationCreator.insert_assignment, record)
            assignment_count = assignment_count + 1

        connection.commit()
        cursor.close()
        counts_message = 'Assigned %s / %s samples to an annotated stratum.'
        logger.info(counts_message, assignment_count, len(specimens))
        SampleStratificationCreator.transcribe_diagnostic_selection_criteria(connection)

    @staticmethod
    def get_interventional_diagnosis(specimen, cursor):
        subject, extraction_date = SampleStratificationCreator.get_source_event(specimen, cursor)
        interventions = SampleStratificationCreator.get_interventions(subject, cursor)
        diagnoses = SampleStratificationCreator.get_diagnoses(subject, cursor)
        position = SampleStratificationCreator.get_interventional_position(
            interventions,
            extraction_date,
        )
        state = SampleStratificationCreator.get_diagnostic_state(extraction_date, diagnoses)
        return position + state

    @staticmethod
    def get_interventional_position(interventions, extraction_date):
        if len(interventions) > 0:
            parts = [i[1] for i in interventions] + [extraction_date]
            valuation_function = SampleStratificationCreator.get_date_valuation(parts)
            if valuation_function is None:
                return ['']
            sequence = sorted(
                interventions + [('source extraction', extraction_date)],
                key=lambda x: valuation_function(x[1]),
            )
            extraction_index = [
                index for index, event in enumerate(sequence)
                if event[0] == 'source extraction'
            ][0]
            earlier_events = [
                event for index, event in enumerate(sequence)
                if index < extraction_index
            ]
            later_events = [
                event for index, event in enumerate(sequence)
                if index > extraction_index
            ]

            if len(earlier_events) > 0 and len(later_events) > 0:
                local_temporal_position_indicator = 'Between interventions'
            elif len(earlier_events) == 0:
                local_temporal_position_indicator = 'Before intervention'
            elif len(later_events) == 0:
                local_temporal_position_indicator = 'After intervention'
            else:
                raise ValueError('Not enough events to calculate interventional position.')
            return [local_temporal_position_indicator]
        return ['']

    @staticmethod
    def get_diagnostic_state(extraction_date, diagnoses):
        logger.debug('Diagnoses:')
        for diagnosis in diagnoses:
            logger.debug(str(diagnosis))
        dates = [extraction_date] + [diagnosis[2] for diagnosis in diagnoses]
        logger.debug('Dates considered: %s', dates)
        valuation_function = SampleStratificationCreator.get_date_valuation(dates)
        if valuation_function is None:
            return ['', '']
        sequence = sorted(diagnoses, key=lambda x: valuation_function(x[2]))
        influenced_diagnoses = []
        for diagnosis in sequence:
            if valuation_function(diagnosis[2]) >= valuation_function(extraction_date):
                influenced_diagnoses.append(diagnosis)
        if len(influenced_diagnoses) > 0:
            diagnosis = influenced_diagnoses[0]
            return [diagnosis[0], diagnosis[1]]
        return ['', '']

    @staticmethod
    def get_date_valuation(dates) -> Callable[[str], Any] | None:

        def iso_valuation(date) -> tuple[int, ...]:
            parts = date.split('-')
            if len(parts) < 2:
                raise ValueError('Only one hyphen-delimited part, not an ISO 8601 date.')
            numeric_parts = []
            for _, part in enumerate(parts):
                stripped = part.lstrip('0')
                if stripped.isnumeric():
                    numeric_parts.append(int(stripped))
                else:
                    raise ValueError(f'Part {part} of date is not numeric.')
            return tuple(numeric_parts)

        def numeric_valuation(date) -> float:
            return float(date)

        def timepoint_extractor(date) -> str:
            match = re.search(r'timepoint [\d]+$', date)
            if match:
                return match.group()
            raise ValueError('Not marked with an explicit timepoint.')

        for valuation in [iso_valuation, numeric_valuation, timepoint_extractor]:
            if all(SampleStratificationCreator.is_convertible(date, valuation) for date in dates):
                return valuation
        logger.warning('No order could be determined among: %s', dates)
        return None

    @staticmethod
    def is_convertible(string, valuation):
        try:
            valuation(string)
            return True
        except ValueError:
            return False

    @staticmethod
    def get_unassigned_specimen_ids(cursor):
        all_specimens = SampleStratificationCreator.get_specimen_ids(cursor)
        cursor.execute('SELECT sample FROM sample_strata;')
        rows = cursor.fetchall()
        assigned = set(row[0] for row in rows)
        logger.debug('Samples already assigned to strata: %s', assigned)
        return sorted(list(set(all_specimens).difference(assigned)))

    @staticmethod
    def get_specimen_ids(cursor):
        cursor.execute('SELECT specimen FROM specimen_collection_process ORDER BY specimen;')
        rows = cursor.fetchall()
        return [row[0] for row in rows]

    @staticmethod
    def get_last_assigned_stratum_identifier(cursor):
        cursor.execute('SELECT stratum_identifier FROM sample_strata;')
        rows = cursor.fetchall()
        identifiers = [int(row[0]) for row in rows]
        if len(identifiers) == 0:
            return 0
        return max(identifiers)

    @staticmethod
    def get_source_event(specimen, cursor):
        cursor.execute(
            'SELECT source, extraction_date FROM specimen_collection_process WHERE specimen=%s ;',
            (specimen,),
        )
        rows = cursor.fetchall()
        return rows[0]

    @staticmethod
    def get_interventions(subject, cursor):
        cursor.execute(
            'SELECT specifier, date FROM intervention WHERE subject=%s ;',
            (subject,),
        )
        rows = cursor.fetchall()
        return rows

    @staticmethod
    def get_diagnoses(subject, cursor):
        cursor.execute(
            'SELECT condition, result, date_of_evidence FROM diagnosis WHERE subject=%s ;',
            (subject,),
        )
        rows = cursor.fetchall()
        return [list(row) for row in rows]

    @staticmethod
    def transcribe_diagnostic_selection_criteria(connection):
        sample_strata = pd.read_sql('SELECT * FROM sample_strata', connection)
        columns = [
            'stratum_identifier',
            'local_temporal_position_indicator',
            'subject_diagnosed_condition',
            'subject_diagnosed_result',
        ]
        sample_strata = sample_strata.drop_duplicates(columns)
        condition_parameters = zip(
            sample_strata.subject_diagnosed_condition,
            sample_strata.local_temporal_position_indicator,
        )
        condition = [f'{x}_{y}' for x, y in condition_parameters]
        diagnostic_selection_criterion = pd.DataFrame({
            'identifier': sample_strata.stratum_identifier,
            'condition': condition,
            'result': sample_strata.subject_diagnosed_result,
        })
        values = [tuple(x) for x in diagnostic_selection_criterion.to_numpy()]
        cursor = connection.cursor()
        cursor.execute('SELECT identifier FROM diagnostic_selection_criterion;')
        existing_criteria = [row[0] for row in cursor.fetchall()]
        values = [v for v in values if v[0] not in existing_criteria]
        insert_query = '''
        INSERT INTO
        diagnostic_selection_criterion (identifier, condition, result)
        VALUES (%s, %s, %s)
        ;
        '''
        cursor.executemany(insert_query, values)
        cursor.close()
        connection.commit()
