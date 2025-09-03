"""CLI utility to stress the backend and database for testing."""
from argparse import ArgumentParser
from typing import cast
import re
from json import loads as json_loads
from time import time as time_time
from time import sleep
from random import choice as random_choice
from os import environ as os_environ

from requests import get as requests_get
import termplotlib as tpl

from smprofiler.ondemand.phenotype_str import phenotype_to_phenotype_str
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.accessors.study import StudyAccess
from smprofiler.workflow.common.export_features import \
    ADIFeatureSpecificationUploader
from smprofiler.apiserver.request_scheduling.counts_scheduler import CountsScheduler
from smprofiler.apiserver.request_scheduling.proximity_scheduler import ProximityScheduler
from smprofiler.db.ondemand_dropper import OnDemandComputationsDropper
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.credentials import retrieve_credentials_from_file
from smprofiler.db.scripts.interactive_uploader import InteractiveUploader as DatabaseSelector
Printer = DatabaseSelector

def parse_args():
    parser = ArgumentParser(
        prog='smprofiler db load-testing',
        description='Test the backend, including load testing.'
    )
    parser.parse_args()


class QuitRequested(RuntimeError):
    """Raised when the user requests exiting the application."""
    def __init__(self):
        super().__init__('Quit requested.')


class Timer:
    _start: float
    _elapsed_series: list

    def __init__(self):
        self._elapsed_series = []

    def start(self) -> None:
        self._start = time_time()

    def stop(self) -> None:
        self._elapsed_series.append(time_time() - self._start)

    def elapsed_seconds(self) -> float:
        return self._elapsed_series[-1]

    def elapsed_formatted(self) -> str:
        elapsed = self.elapsed_seconds()
        return self.format_elapsed(elapsed)

    def average_elapsed(self) -> float:
        return sum(self._elapsed_series) / len(self._elapsed_series)

    def average_elapsed_formatted(self) -> str:
        return self.format_elapsed(self.average_elapsed())

    def all_elapsed_formatted(self) -> list[str]:
        return [self.format_elapsed(elapsed) for elapsed in self._elapsed_series]

    def reset_all(self) -> None:
        self._start = None
        self._elapsed_series = []

    @staticmethod
    def format_elapsed(elapsed: float) -> str:
        if elapsed < 1.0:
            return f'{round(1000*elapsed)}ms'
        return f'{round(elapsed, ndigits=1)}s'

Size = int
Time = float
SizeMeasurement = tuple[Time, Size]

class QueueSizeChecker:
    size_measurements: list[SizeMeasurement]
    start: float | None

    def __init__(self):
        self.size_measurements = []
        self.start = None

    def measure(self, verbose: bool=True) -> None:
        with DBCursor() as cursor:
            cursor.execute('SELECT sum(get_active_queue_size(schema_name)) FROM default_study_lookup.study_lookup ;')
            rows = tuple(cursor.fetchall())
            size = rows[0][0]
        if self.start is None:
            self.start = time_time()
            timepoint = 0.0
        else:
            timepoint = time_time() - self.start
        measurement = (round(timepoint, ndigits=1), size)
        self.size_measurements.append(measurement)
        if verbose:
            Printer.print(f'\r polling job queue size... (time={measurement[0]}, size={measurement[1]})', end='', style='item')

    def poll(self, interval_seconds: int = 3) -> None:
        last_measurement = None
        repetition_max = 100
        count = 0
        while (last_measurement is None or last_measurement[1] > 0) and count < repetition_max:
            self.measure()
            last_measurement = self.size_measurements[-1]
            count += 1
            sleep(interval_seconds)
        if last_measurement is None:
            Printer.print(f'Warning: Reached poll repetition max {repetition_max}', style='flag')

    def reset(self) -> None:
        self.size_measurements = []


class LoadTester:
    database_selector: DatabaseSelector
    api_url: str | None
    retrieval_timer: Timer

    def __init__(self):
        self.database_selector = DatabaseSelector()
        self.api_url = None
        self.retrieval_timer = Timer()

    def start(self) -> None:
        self.database_selector._assess_database_config_files()
        self.database_selector._solicit_and_ensure_database_selection()
        self._start_tests()

    def _start_tests(self) -> None:
        try:
            self.database_selector._solicit_and_ensure_database_selection()
            database_config_file = cast(str, self.database_selector.selected_database_config_file)
            credentials = retrieve_credentials_from_file(database_config_file)
            os_environ['SINGLE_CELL_DATABASE_HOST'] = credentials.endpoint
            os_environ['SINGLE_CELL_DATABASE_USER'] = credentials.user
            os_environ['SINGLE_CELL_DATABASE_PASSWORD'] = credentials.password
            self._solicit_and_ensure_api_reachable()
            self._print_application_status_summary()
            self._simple_speed_test()
            self._intermediate_speed_test()
            self._large_job_set_speed_test()
            self._intensive_job_set_speed_test()
        except QuitRequested:
            Printer.print('Quit requested.', style='flag')

    def _retrieve(self, subpath: str, arguments: dict | None, verbose=True):
        url = f'http://{self.api_url}/{subpath}'
        if arguments is not None:
            url += '/?' + '&'.join(f'{key}={value}' for key, value in arguments.items())
            url = re.sub(' ', '+', url)
        self.retrieval_timer.start()
        if verbose:
            Printer.print(' Retrieving ', style='popout', end='')
            Printer.print(url, style='item', end='')
            Printer.print(' ... ', style='popout', end='')
        response = requests_get(url)
        if response.status_code != 200:
            Printer.print(f' Got HTTP {response.status_code}', style='flag')
            return None
        if verbose:
            Printer.print('Done. ', style='popout')
        self.retrieval_timer.stop()
        try:
            payload = json_loads(response.text)
            return payload
        except Exception as error:
            print('Got: ' + response.text)
            raise(error)

    def _simple_speed_test(self) -> None:
        Printer.print('', style='message')
        Printer.print('    Basic testing, simple queries'.ljust(80), style='title')
        dataset = 'Breast cancer IMC'
        requests = [
            ('study-summary', {'study': dataset}),
            ('channels', {'study': dataset}),
            ('phenotype-symbols', {'study': dataset}),
        ]
        for request in requests:
            response = self._retrieve(*request)
        phenotype_symbols = tuple(map(lambda item: item['handle_string'], response))
        print('')
        self._print_numbers_and_names([
            ('3 basic requests:', ', '.join(self.retrieval_timer.all_elapsed_formatted())),
            ('Average response time:', self.retrieval_timer.average_elapsed_formatted()),
        ])
        self.retrieval_timer.reset_all()
        print()
        basic = 50
        Printer.print(f'{basic} basic requests with no waiting...', style='message')
        total = Timer()
        total.start()
        for i in range(basic):
            print(f'\r{i+1}', end='')
            identifier = random_choice(phenotype_symbols)
            self._retrieve('phenotype-criteria', {'study': dataset, 'phenotype_symbol': identifier}, verbose=False)
        print('\r      ')
        total.stop()
        self._print_numbers_and_names([
            ('Average response time:', self.retrieval_timer.average_elapsed_formatted()),
            ('Total response time:', total.elapsed_formatted()),
        ])

    def _drop_fractions_feature(self, details) -> None:
        study = details['study']
        with DBCursor(study=study) as cursor:
            get = ADIFeatureSpecificationUploader.get_data_analysis_study
            measurement_study_name = StudyAccess(cursor).get_study_components(study).measurement
            data_analysis_study = get(measurement_study_name, cursor)

        specification = CountsScheduler._get_feature_specification(
            study,
            data_analysis_study,
            PhenotypeCriteria(positive_markers=(details['positive_marker'],), negative_markers=(details['negative_marker'],)),
            (),
        )
        if specification is None:
            return
        with DBCursor(study=study) as cursor:
            OnDemandComputationsDropper.drop_features(cursor, [specification], just_features=True, verbose=False)

    def _drop_proximity_feature(self, details) -> None:
        study = details['study']
        with DBCursor(study=study) as cursor:
            get = ADIFeatureSpecificationUploader.get_data_analysis_study
            measurement_study_name = StudyAccess(cursor).get_study_components(study).measurement
            data_analysis_study = get(measurement_study_name, cursor)

        phenotype1 = PhenotypeCriteria(positive_markers=(details['positive_marker'],), negative_markers=(details['negative_marker'],))
        phenotype2 = PhenotypeCriteria(positive_markers=(details['positive_marker2'],), negative_markers=(details['negative_marker2'],))
        p1 = phenotype_to_phenotype_str(phenotype1)
        p2 = phenotype_to_phenotype_str(phenotype2)
        radius = details['radius']
        specification = ProximityScheduler._get_feature_specification(
            study,
            data_analysis_study,
            p1,
            p2,
            radius,
        )
        if specification is None:
            return
        with DBCursor(study=study) as cursor:
            OnDemandComputationsDropper.drop_features(cursor, [specification], just_features=True, verbose=False)

    def _intermediate_speed_test(self) -> None:
        Printer.print('', style='message')
        Printer.print('    Intermediate non-trivial metrics computation, speed test'.ljust(80), style='title')
        Printer.print('Test example is a ', end='', style='message')
        Printer.print('phenotype fractions', end='', style='popout')
        Printer.print(' metric.', style='message')
        checker = QueueSizeChecker()
        checker.measure(verbose=False)
        if not checker.size_measurements[-1][1] == 0:
            Printer.print('Warning: There is a non-trivial job queue already, testing aborted.', style='flag')
            return
        checker.reset()
        dataset = 'Breast cancer IMC'
        details = {'study': dataset, 'positive_marker': 'TWIST1', 'negative_marker': 'VWF'}
        Printer.print('Dropping test example computed feature, if it exists.', style='message')
        self._drop_fractions_feature(details)
        self._retrieve('phenotype-counts', details)
        checker.poll()
        Printer.print('', style='message')

        self._show_clearance_rate(checker.size_measurements)

        Printer.print('Cleaning up test example computed feature... ', end='', style='item')
        self._drop_fractions_feature(details)
        Printer.print('Done.', style='item')

    def _show_clearance_rate(self, measurements) -> None:
        max_time = max(m[0] for m in measurements)
        max_size = max(m[1] for m in measurements)
        jobs_per_minute = round(max_size/(max_time/60), ndigits=1)
        fig = tpl.figure()
        fig.plot(
            *list(zip(*measurements)),
            xlim=(0, max_time),
            ylim=(0, max_size),
            label='Number of jobs in queue',
            xlabel='Time since computation request (seconds)',
            title=f'Jobs cleared on average at {jobs_per_minute} jobs / minute',
            width=120,
            height=25,
        )
        fig.show()
        Printer.print('Average clearance rate: ', end='', style='message')
        Printer.print(f'{jobs_per_minute}', end='', style='popout')
        Printer.print(' jobs per minute. ', end='', style='message')
        Printer.print(f'{max_size}', end='', style='popout')
        Printer.print(f' jobs in ', end='', style='message')
        Printer.print(f'{max_time}', end='', style='popout')
        Printer.print(' seconds.', style='message')
        Printer.print('', style='message')

    def _large_job_set_speed_test(self) -> None:
        Printer.print('', style='message')
        Printer.print('    Large job-set metrics computation, speed test'.ljust(80), style='title')
        Printer.print('Test examples are ', end='', style='message')
        Printer.print('phenotype fractions', end='', style='popout')
        Printer.print(' metrics.', style='message')
        checker = QueueSizeChecker()
        checker.measure(verbose=False)
        if not checker.size_measurements[-1][1] == 0:
            Printer.print('Warning: There is a non-trivial job queue already, testing aborted.', style='flag')
            return
        checker.reset()
        dataset = 'LUAD progression'
        details_list = [
            {'study': dataset, 'positive_marker': 'MPO', 'negative_marker': 'KIT'},
            {'study': dataset, 'positive_marker': 'ITGAX', 'negative_marker': 'MPO'},
            {'study': dataset, 'positive_marker': 'KLRD1', 'negative_marker': 'CD14'},
            {'study': dataset, 'positive_marker': 'KIT', 'negative_marker': 'MPO'},
        ]
        Printer.print('Dropping test example computed features, if they exists.', style='message')
        for details in details_list:
            self._drop_fractions_feature(details)

        for details in details_list:
            self._retrieve('phenotype-counts', details)
        checker.poll()
        Printer.print('', style='message')

        self._show_clearance_rate(checker.size_measurements)

        Printer.print('Cleaning up test example computed feature... ', end='', style='item')
        self._drop_fractions_feature(details)
        Printer.print('Done.', style='item')

    def _intensive_job_set_speed_test(self) -> None:
        Printer.print('', style='message')
        Printer.print('    Intensive job-set metrics computation, speed test'.ljust(80), style='title')
        Printer.print('Test example is a ', end='', style='message')
        Printer.print('proximity', end='', style='popout')
        Printer.print(' metric.', style='message')
        checker = QueueSizeChecker()
        checker.measure(verbose=False)
        if not checker.size_measurements[-1][1] == 0:
            Printer.print('Warning: There is a non-trivial job queue already, testing aborted.', style='flag')
            return
        checker.reset()
        with DBCursor() as cursor:
            cursor.execute('SELECT study FROM default_study_lookup.study_lookup WHERE schema_name=\'orion_crc\';')
            dataset = tuple(cursor.fetchall())[0][0]
        details_list = [
            {
                'study': dataset,
                'positive_marker': 'PDL1',
                'negative_marker': 'SMA',
                'positive_marker2': 'MKI67',
                'negative_marker2': 'SMA',
                'feature_class': 'proximity',
                'radius': '30.0',
            },
        ]
        Printer.print('Dropping test example computed features, if they exists.', style='message')
        for details in details_list:
            self._drop_proximity_feature(details)    
        for details in details_list:
            self._retrieve('request-spatial-metrics-computation-custom-phenotypes', details)
        checker.poll()
        Printer.print('', style='message')

        self._show_clearance_rate(checker.size_measurements)

        Printer.print('Cleaning up test example computed feature... ', end='', style='item')
        self._drop_proximity_feature(details)
        Printer.print('Done.', style='item')

    def _print_application_status_summary(self) -> None:
        with DBCursor() as cursor:
            cursor.execute('SELECT schema_name, get_queue_size(schema_name) AS queue_size FROM default_study_lookup.study_lookup ;')
            rows = tuple(cursor.fetchall())
        Printer.print('Number of pending jobs, including failed (abandoned, reached maximum retries):', style='message')
        self._print_numbers_and_names(rows)
        print('')
        with DBCursor() as cursor:
            cursor.execute('SELECT schema_name, get_active_queue_size(schema_name) AS active_queue_size FROM default_study_lookup.study_lookup ;')
            rows = tuple(cursor.fetchall())
        Printer.print('Number of fresh pending jobs with no retries:', style='message')
        self._print_numbers_and_names(rows)

    def _print_numbers_and_names(self, rows) -> None:
        for row in rows:
            Printer.print(row[0].ljust(30), end='', style='fieldname')
            Printer.print(' ', end='', style='message')
            Printer.print(str(row[1]).rjust(6), style='message')

    def _solicit_and_ensure_api_reachable(self) -> None:
        default_value = 'smprofiler.io/api'
        while self.api_url is None:
            Printer.print('Select API server', 'prompt', end='')
            Printer.print(f' [default selection ', 'prompt', end='')
            Printer.print(f'{default_value}', 'item', end='')
            Printer.print(']', 'prompt', end='')
            Printer.print(': ', 'prompt', end='')
            answer = input()
            if answer == 'q':
                raise QuitRequested
            if answer in ['', '\n']:
                selection = default_value
            else:
                selection = answer
            metadata, validated = self._validate_api_server(selection)
            if validated:
                self.api_url = selection
                Printer.print('Selected server: ', end='', style='message')
                Printer.print(self.api_url, style='fieldname')
                Printer.print('API version:     ', end='', style='message')
                Printer.print(metadata['version'], style='fieldname')

    def _validate_api_server(self, server: str) -> tuple[dict, bool]:
        server = re.sub(r'^https?://', '', server)
        server = re.sub(r'/$', '', server)
        try:
            response = requests_get(f'http://{server}')
            if response.status_code != 200:
                Printer.print(f'This server is not reachable or unavailable (HTTP {response.status_code}).', style='flag')
            response = requests_get(f'http://{server}/openapi.json')
            if response.status_code != 200:
                Printer.print(f'This server does not advertisee an openapi.json description (HTTP {response.status_code}).', style='flag')
                return ({}, False)
        except ValueError as error:
            Printer.print(f'Something went wrong trying to reach this server.', style='flag')
            print(error)
            return ({}, False)
        except:
            Printer.print(f'Something went wrong with the connection while trying to reach this server.', style='flag')
            return ({}, False)
        data = json_loads(response.text)
        if not 'info' in data:
            Printer.print(f'"info" field missing from response.', style='flag')
            return ({}, False)
        if not 'version' in data['info']:
            Printer.print(f'"version" field missing from response.', style='flag')
            return ({}, False)
        version = data['info']['version']
        if not 'title' in data['info']:
            Printer.print(f'"title" field missing from response.', style='flag')
            return ({}, False)
        title = data['info']['title']
        expected = 'Single cell studies data API'
        if not title == expected:
            Printer.print(f'API server is not recognizable as the SMProfiler application server. Got title: ', end='', style='message')
            Printer.print(title, style='item')
            return ({}, False)
        return ({'version': version}, True)


def main():
    parse_args()
    gui = LoadTester()
    try:
        gui.start()
    except KeyboardInterrupt:
        Printer.print('\nCancelled by user request.', style='flag')


if __name__=='__main__':
    main()
