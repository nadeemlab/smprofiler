"""CLI utility to cache a randam subsample of all cells for given studies."""
from os import listdir
from os.path import expanduser
from os.path import isfile
from os.path import basename
from os.path import join
from os.path import split
import re
from sys import exit as sys_exit
import argparse

from psycopg import connect


from smprofiler.db.database_connection import retrieve_study_names
from smprofiler.db.representative_subsample import Subsampler
from smprofiler.db.representative_subsample import DEFAULT_MAX
from smprofiler.db.credentials import DBCredentials
from smprofiler.db.credentials import retrieve_credentials_from_file
from smprofiler.db.credentials import MissingKeysError
from smprofiler.standalone_utilities.log_formats import CustomFormatter

PREVIOUS_FILENAME = '.smprofiler_last_used_config'


def parse_args():
    parser = argparse.ArgumentParser(
        prog='smprofiler db cache-subsample',
        description='Cache a random subsample of cells.'
    )
    parser.add_argument(
        'maximum_number_cells',
        type=int,
        nargs='?',
        const=1,
        default=DEFAULT_MAX,
        help='The maximum number of cells to subsample from each dataset.',
    )
    parser.add_argument(
        '--database-config-file',
        nargs='?',
        help='If supplied, will use non-interactive mode.'
    )
    parser.add_argument(
        '--only-uncreated',
        action='store_true',
        help='If supplied, only studies with no current cached downsampling will be considered.'
    )
    return parser.parse_args()


class QuitRequested(RuntimeError):
    """Raised when the user requests exiting the application."""
    def __init__(self):
        super().__init__('Quit requested.')


class InteractiveSubsampler:
    selected_database_config_file: str | None
    connectables: tuple[str, ...]
    credentials: DBCredentials | None
    maximum_number_cells: int
    only_uncreated: bool

    def __init__(self, maximum_number_cells: int, only_uncreated: bool):
        self.selected_database_config_file = None
        self.connectables = ()
        self.maximum_number_cells = maximum_number_cells
        self.only_uncreated = only_uncreated

    def start(self) -> None:
        self._initial_assessment_of_available_options()
        self._enter_loop()

    def _initial_assessment_of_available_options(self) -> None:
        self.print('(Enter "q" to quit.)\n', style='message')
        self._assess_database_config_files()

    def _assess_database_config_files(self) -> None:
        home = expanduser('~')
        considered = [join(home, f) for f in listdir(home)] + listdir('.')
        filename_matches = tuple(filter(
            lambda filename: re.search(r'^\.smprofiler_db.config', basename(filename)),
            filter(isfile, considered),
        ))
        if len(filename_matches) == 0:
            self.print('No database config files ', style='message', end='')
            self.print('(named like ', style='message', end='')
            self.print('.smprofiler_db.config', style='popout', end='')
            self.print('...) were found in home directory or current working directory.', style='message')
            sys_exit(1)
        format_matches = tuple(filter(self._check_database_config_file_format, filename_matches))
        if len(format_matches) < len(filename_matches):
            print('')
        connectables = tuple(sorted(list(filter(self._check_connectability, format_matches))))
        if len(connectables) < len(format_matches):
            print('')
        self._report_validated_config_files(connectables)
        if len(connectables) == 1:
            file = connectables[0]
            self._select_config_file(file)
        else:
            self.connectables = connectables

    def _select_config_file(self, file: str) -> None:
        path, filename = split(file)
        self.print('Using ', style='message', end='')
        self.print(f'{path}{"/" if not path == "" else "./"}', style='fieldname', end='')
        self.print(f'{filename}', style='popout')
        print()
        self.selected_database_config_file = file
        self._record_selected_database_config_file(file)

    def _get_previous_database_config_file(self) -> str | None:
        file = join(expanduser('~'), PREVIOUS_FILENAME)
        if isfile(file):
            with open(file, 'rt', encoding='utf-8') as f:
                name = f.read()
            return name
        return None

    def _record_selected_database_config_file(self, filename: str) -> None:
        file = join(expanduser('~'), PREVIOUS_FILENAME)
        with open(file, 'wt', encoding='utf-8') as f:
            f.write(filename)
        self.credentials = retrieve_credentials_from_file(filename)

    def _report_validated_config_files(self, validated: tuple[str, ...]) -> None:
        self.print('    Target database'.ljust(80), 'title')
        print()
        self.print('Found database config files with correct format and validated credentials:', style='message')
        previous = self._get_previous_database_config_file()
        self._print_paths(validated, previous)
        print('')
        if previous is not None:
            self.print('The previously-used credentials file is marked with *.', 'message')
            print('')

    def _print_paths(self, paths: tuple[str, ...], indicated_item: str | None) -> None:
        pairs = [split(f) for f in paths]
        width = 2 + max([len(pair[0]) for pair in pairs])
        for i, (path, filename) in enumerate(pairs):
            if join(path, filename) == indicated_item:
                ordinal = f'*{i} '
            else:
                ordinal = f'{i} '
            self.print(ordinal.rjust(3), style='item', end='')
            self.print(f' {path}{"/" if not path == "" else "./"}'.rjust(width), style='fieldname', end='')
            self.print(f'{filename}', style='popout')

    def _check_database_config_file_format(self, filename: str) -> bool:
        try:
            retrieve_credentials_from_file(filename)
        except MissingKeysError as error:
            self.print(f'Warning: ', style='flag', end='')
            self.print(f'{filename}', style='popout', end='')
            self.print(f' is missing keys: ', style='message', end='')
            self.print(", ".join(list(error.missing)), style='item')
            return False
        return True

    def _check_connectability(self, file: str) -> bool:
        credentials = retrieve_credentials_from_file(file)
        try:
            with connect(
                dbname='smprofiler_datasets',
                host=credentials.endpoint,
                user=credentials.user,
                password=credentials.password,
            ) as _:
                return True
        except Exception:
            pass
        self.print(f'Warning: ', style='flag', end='')
        self.print(f' credentials are invalid or database ', style='message', end='')
        self.print('smprofiler_datasets', style='item', end='')
        self.print(f' does not exist in ', style='message', end='')
        self.print(f'{file}', style='popout')
        return False

    def _enter_loop(self) -> None:
        quit_requested = False
        while not quit_requested:
            quit_requested = self._cache_loop()
        self.print('Finished.', style='message')

    def _cache_loop(self) -> bool:
        for step in (
            self._solicit_and_ensure_database_selection,
        ):
            try:
                step()
            except QuitRequested:
                return True
        try:
            proceed = self._solicit_confirmation_of_action()
        except QuitRequested:
            self.print('Dataset caching not scheduled.', 'flag')
            return True
        if proceed:
            self._do_specified_caching()
            return True
        return False

    def _solicit_and_ensure_database_selection(self) -> None:
        while self.selected_database_config_file is None:
            self.print('Select database config file', 'prompt', end='')
            previous_index = self._get_previous_index()
            if previous_index is not None:
                self.print(f' [default selection ', 'prompt', end='')
                self.print(f'{previous_index}', 'item', end='')
                self.print(']', 'prompt', end='')
            self.print(': ', 'prompt', end='')
            answer = input()
            if answer == 'q':
                raise QuitRequested
            if answer in ['', '\n'] and previous_index is not None:
                self._select_config_file(self.connectables[previous_index])
                continue
            try:
                index = int(answer)
            except ValueError:
                self.print('Enter a valid index', 'flag')
                continue
            if index < 0 or index >= len(self.connectables):
                self.print('Enter a valid index', 'flag')
                continue
            self._select_config_file(self.connectables[index])

    def _get_previous_index(self) -> int | None:
        previous = self._get_previous_database_config_file()
        if previous is None:
            return None
        for i, connectable in enumerate(self.connectables):
            if connectable == previous:
                return i
        return None

    def _solicit_confirmation_of_action(self) -> bool:
        self._announce_plan()
        self.print('Proceed? [', 'prompt', end='')
        self.print('y', 'yes', end='')
        self.print('/', 'prompt', end='')
        self.print('n', 'no', end='')
        self.print('] (default no) ', 'prompt', end='')
        answer = input()
        print()
        if answer in ('y', 'Y', 'yes'):
            return True
        if answer == 'q':
            raise QuitRequested
        self.selected_dataset_source = None
        self.selected_database_config_file = None
        self.sourceables = ()
        return False

    def _announce_plan(self) -> None:
        self.print('  Subsampling'.ljust(80), 'title')
        print()
        self.print(f'Will subsample {self.maximum_number_cells} cells from each dataset '.ljust(26), 'message', end='')
        self.print('and save to the database at'.ljust(26), 'message', end='')
        assert self.credentials is not None
        self.print(f'  {self.credentials.endpoint}', 'item', end='')
        self.print(f'  (from credentials ', 'message', end='')
        self.print(f'{self.selected_database_config_file}', 'popout', end='')
        self.print(f' )', 'message')
        print()

    def _do_specified_caching(self) -> None:
        InteractiveSubsampler.do_specified_caching(self.selected_database_config_file, self.maximum_number_cells, self.only_uncreated, True)

    @classmethod
    def do_specified_caching(cls, database_config_file: str | None, maximum_number_cells: int, only_uncreated: bool, verbose: bool) -> None:
        def abbreviate(s: str) -> str:
            if len(s) > 40:
                return s[0:39] + '...'
            return s
        for study in retrieve_study_names(database_config_file):
            if only_uncreated and Subsampler.cache_exists(study, database_config_file):
                InteractiveSubsampler.print(f'Skipping "{study}" because cache exists.', 'message')
                continue
            InteractiveSubsampler.print(f'Processing study ', 'message', end='')
            InteractiveSubsampler.print(f'{abbreviate(study)}', 'popout', end='')
            InteractiveSubsampler.print(f' ', 'message')
            f = database_config_file
            Subsampler(study, f, maximum_number_cells=maximum_number_cells, verbose=verbose)

    @staticmethod
    def print(message: str, style: str | None, end: str = '\n') -> None:
        codes = {
            None: '',
            'title': '\033[7;36m',
            'fieldname': '\033[100;97m',
            'emphfieldname': '\033[32m',
            'message': '',
            'popout': CustomFormatter.magenta,
            'item': CustomFormatter.blue,
            'dataset source': CustomFormatter.yellow,
            'order': '\033[100;97m',
            'prompt': '',
            'flag': CustomFormatter.red,
            'no': CustomFormatter.red,
            'yes': CustomFormatter.green,
        }
        reset = CustomFormatter.reset
        print(f'{codes[style]}{message}{reset}', end=end)


def main():
    args = parse_args()
    if args.database_config_file is not None:
        InteractiveSubsampler.do_specified_caching(expanduser(args.database_config_file), args.maximum_number_cells, args.only_uncreated, True)
    else:
        gui = InteractiveSubsampler(args.maximum_number_cells, args.only_uncreated)
        try:
            gui.start()
        except KeyboardInterrupt:
            InteractiveSubsampler.print('\nCancelled by user request.', style='flag')


if __name__=='__main__':
    main()
