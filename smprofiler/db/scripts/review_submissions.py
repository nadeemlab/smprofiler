"""CLI utility to review and annotate result submissions."""
from datetime import datetime
from datetime import timezone
from argparse import ArgumentParser
from typing import cast
from os import environ as os_environ
from os import system as os_system
from os.path import expanduser
from warnings import filterwarnings
from warnings import catch_warnings
import re
import string
import time
import sys

from pandas import read_sql  # type: ignore
from pandas import DataFrame
from pandas import Series
from pandas import isnull as is_nat

from smprofiler.standalone_utilities.timestamping import now
from smprofiler.standalone_utilities.timestamping import GUESSED_LOCAL_TIMEZONE
from smprofiler.db.exchange_data_formats.findings import FindingStatus
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.credentials import retrieve_credentials_from_file
from smprofiler.db.scripts.interactive_uploader import InteractiveUploader as DatabaseSelector
Printer = DatabaseSelector

def getch():
    import sys, termios

    fd = sys.stdin.fileno()
    orig = termios.tcgetattr(fd)

    new = termios.tcgetattr(fd)
    new[3] = new[3] & ~termios.ICANON
    new[6][termios.VMIN] = 1
    new[6][termios.VTIME] = 0

    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, new)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, orig)

def prefilled_input(prompt, prefill=''):
    buffer = prefill
    print(prompt + buffer, end='', flush=True)
    while True:
        c = getch()
        if c == '\n':
            break
        if not (c in string.printable or c == '\x7f'):
            continue
        if c == '\x7f':
            if len(buffer) > 0:
                buffer = buffer[0:-1]
        else:
            buffer = buffer + c
        print('\33[2K\r', end='')
        print(prompt + buffer, end='', flush=True)
    print('', flush=True)
    return buffer

def parse_args():
    parser = ArgumentParser(
        prog='smprofiler db review-submissions',
        description='Review and annotates results/findings submissions.'
    )
    parser.parse_args()


class QuitRequested(RuntimeError):
    """Raised when the user requests exiting the application."""
    def __init__(self):
        super().__init__('Quit requested.')


class Reviewer:
    database_selector: DatabaseSelector
    findings: DataFrame
    finding_id: int
    finding: Series

    def __init__(self):
        self.database_selector = DatabaseSelector()

    def start(self) -> None:
        self.database_selector._assess_database_config_files()
        self.database_selector._solicit_and_ensure_database_selection()
        self._start_review_loop()

    def _start_review_loop(self) -> None:
        try:
            database_config_file = cast(str, self.database_selector.selected_database_config_file)
            credentials = retrieve_credentials_from_file(database_config_file)
            os_environ['SINGLE_CELL_DATABASE_HOST'] = credentials.endpoint
            os_environ['SINGLE_CELL_DATABASE_USER'] = credentials.user
            os_environ['SINGLE_CELL_DATABASE_PASSWORD'] = credentials.password
            self._print_findings()
            self._accept_commands()
        except QuitRequested:
            Printer.print('Quit requested.', style='flag')

    def _retrieve_findings(self) -> None:
        with DBConnection() as connection:
            with catch_warnings():
                filterwarnings('ignore', message='pandas only supports SQLAlchemy', category=UserWarning)
                self.findings = read_sql('SELECT * from default_study_lookup.finding;', connection)

    def _format_value(self, value) -> str:
        if isinstance(value, datetime) and GUESSED_LOCAL_TIMEZONE is not None:
            if is_nat(value):
                return ''
            d = value.replace(tzinfo=timezone.utc).astimezone(GUESSED_LOCAL_TIMEZONE)
            return d.strftime('%a %d %b %Y, %I:%M%p')
        return str(value)

    def _print_findings(self) -> None:
        Printer.print('    Findings'.ljust(80), 'title')
        self._retrieve_findings()
        for study, df in self.findings.groupby('study'):
            Printer.print(study, style='popout')
            for i, row in df.sort_values(by='id').iterrows():
                self._print_numbers_and_names(zip(df.columns, [x for x in row]))
                print('')

    def _select_finding(self) -> None:
        finding_id = None
        known_ids = set(map(int, self.findings['id']))
        while finding_id is None:
            Printer.print('Enter finding id', 'prompt', end='')
            Printer.print(': ', 'prompt', end='')
            response = input()
            if not re.match('^[1-9][0-9]*$', response):
                continue
            numeral = int(response)
            if numeral in known_ids:
                finding_id = numeral
        f = self.findings[self.findings['id'] == finding_id].squeeze()
        self._print_numbers_and_names(zip(f.index, f.values), style='emphfieldname')
        self.finding_id = finding_id
        self.finding = f

    def _revise_sentence(self) -> None:
        confirmed = False
        while not confirmed:
            sentence = self.finding['description']
            revision = prefilled_input('Enter sentence description: ', prefill=sentence)
            Printer.print('New sentence: ', style='message', end='')
            Printer.print(revision, style='popout')
            confirmed = self._confirm()
        if sentence == revision:
            Printer.print('No change.', style='flag')
            return
        with DBCursor() as cursor:
            cursor.execute('UPDATE default_study_lookup.finding SET description=%s WHERE id=%s;', (revision, self.finding_id))

    def _revise_background(self) -> None:
        confirmed = False
        while not confirmed:
            background = self.finding['background']

            filename = expanduser('~/._background.tmp.smprofiler.txt')
            with open(filename, 'wt', encoding='utf-8') as file:
                file.write(background.rstrip())
            os_system(f'nano -$ {filename}')
            with open(filename, 'rt', encoding='utf-8') as file:
                revision = file.read().rstrip()

            Printer.print('New background: ', style='message', end='')
            Printer.print(revision, style='popout')
            confirmed = self._confirm()
        if background == revision:
            Printer.print('No change.', style='flag')
            return
        with DBCursor() as cursor:
            cursor.execute('UPDATE default_study_lookup.finding SET background=%s WHERE id=%s;', (revision, self.finding_id))

    def _update_status(self, value: FindingStatus) -> None:
        Printer.print(f'Setting finding {self.finding_id} status to: ', 'message', end='')
        Printer.print(value.value, 'popout')
        confirmed = self._confirm()
        if not confirmed:
            Printer.print('Canceling.', 'flag')
            return
        with DBCursor() as cursor:
            cursor.execute('UPDATE default_study_lookup.finding SET status=%s WHERE id=%s;', (value.value, self.finding_id))
        if value == FindingStatus.published:
            with DBCursor() as cursor:
                cursor.execute('SELECT publication_datetime FROM default_study_lookup.finding WHERE id=%s;', (self.finding_id,))
                publication_datetime = tuple(cursor.fetchall())[0][0]
                if publication_datetime == None:
                    publication_datetime = now()
                    cursor.execute('UPDATE default_study_lookup.finding SET publication_datetime=%s WHERE id=%s;', (publication_datetime, self.finding_id))
                    Printer.print('Set publication datetime: ', end='', style='message')
                    Printer.print(self._format_value(publication_datetime.astimezone(timezone.utc)), style='popout')
                else:
                    Printer.print('Already published, not updating publication datetime.', style='flag')

    def _delete_permanently(self) -> None:
        Printer.print(f'Permanently deleting finding {self.finding_id} submitted by ', 'message', end='')
        Printer.print(self.finding['email'], 'popout')
        confirmed = self._confirm()
        if not confirmed:
            Printer.print('Canceling.', 'flag')
            return
        with DBCursor() as cursor:
            cursor.execute('DELETE FROM default_study_lookup.finding WHERE id=%s;', (self.finding_id,))
        print('Done.')

    def _accept_commands(self) -> None:
        self._select_finding()
        action = None
        while action is None:
            answer = input('e - edit description   b - edit background   d - defer decision   D - delete permanently   r - reject   p - publish: ')
            if answer in ['e', 'b', 'd', 'D', 'r', 'p']:
                action = answer
        if action == 'e':
            self._revise_sentence()
        if action == 'b':
            self._revise_background()
        if action == 'D':
            self._delete_permanently()
        status = {
            'd': FindingStatus.deferred_decision,
            'r': FindingStatus.rejected,
            'p': FindingStatus.published,
        }
        if action in status:
            s = status[action]
            self._update_status(s)

    def _confirm(self) -> bool:
        Printer.print('Proceed? [', 'prompt', end='')
        Printer.print('y', 'yes', end='')
        Printer.print('/', 'prompt', end='')
        Printer.print('n', 'no', end='')
        Printer.print('] (default no) ', 'prompt', end='')
        answer = input()
        print()
        if answer in ('y', 'Y', 'yes'):
            return True
        if answer == 'q':
            raise QuitRequested
        return False

    def _print_numbers_and_names(self, rows, style: str = 'message') -> None:
        for row in rows:
            Printer.print(row[0].ljust(30), end='', style='fieldname')
            Printer.print(' ', end='', style='message')
            Printer.print(self._format_value(row[1]), style=style)


def main():
    parse_args()
    gui = Reviewer()
    try:
        gui.start()
    except KeyboardInterrupt:
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            pass
        Printer.print('\nCancelled by user request.', style='flag')
        sys.exit()

if __name__=='__main__':
    main()
