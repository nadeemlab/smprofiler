"""CLI utility to drop one feature (values, specification, specifiers) from the database"""

import argparse
from typing import cast
from sys import exit as sys_exit

from attr import define
from pandas import DataFrame
from pandas import read_sql

from smprofiler.db.database_connection import get_and_validate_database_config
from smprofiler.db.database_connection import DBCursor
from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler.standalone_utilities.log_formats import CustomFormatter

def parse_args():
    parser = argparse.ArgumentParser(
        prog='smprofiler db delete-feature',
        description='Drop one quantitative feature, including all specifiers and values.'
    )
    parser.add_argument(
        '--specification',
        dest='specification',
        help='The feature specification identifier, typically a decimal integer string.',
        required=False,
    )
    add_argument(parser, 'database config')
    parser.add_argument(
        '--study-name',
        dest='study_name',
        help='The name of the study for which the feature was computed.',
    )
    parser.add_argument(
        '--bulk-null',
        dest='bulk_null',
        help='If set, try to find corrupt features in bulk to delete.',
        action='store_true',
    )
    return parser.parse_args()

@define
class SuspiciousFeature:
    feature: int
    number_null: int
    number_complete: int
    total_expected: int
    study: str

class BulkDropper:
    database_config_file: str
    suspicious: tuple[SuspiciousFeature]
    minimum_null: int
    minimum_fraction_null: float
    fraction_missing: float

    def __init__(self, database_config_file: str):
        self.database_config_file = database_config_file
        self.minimum_null = 0
        self.minimum_fraction_null = 0
        self.fraction_missing = 0
        self._start()

    def _start(self) -> None:
        self._determine_suspicious_features()
        self._show_features()
        self._solicit_parameters()
        self._show_features()
        self._confirm_delete()
        self._do_delete()

    def _determine_suspicious_features(self) -> None:
        with DBCursor(database_config_file=self.database_config_file) as cursor:
            cursor.execute('SELECT study FROM study_lookup;')
            studies = tuple(map(lambda s: s[0], tuple(cursor.fetchall())))
        suspicious = []
        for study in studies:
            with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
                cursor.execute('SELECT COUNT(*) FROM specimen_data_measurement_process;')
                count = tuple(cursor.fetchall())[0][0]
                df = read_sql('SELECT feature, value is null as isnull FROM quantitative_feature_value;', cursor.connection)
            for feature, group in df.groupby('feature'):
                n1 = sum(group['isnull'])
                n2 = group.shape[0] - n1
                if n1 == 0 and n2 == count:
                    continue
                suspicious.append(SuspiciousFeature(feature, n1, n2, count, study))
        self.suspicious = tuple(suspicious)

    def _show_features(self) -> None:
        filtered = self._get_suspicious()
        for s in filtered:
            print(f'{s.feature}: {s.number_null} null, {s.number_complete} not  (of {s.total_expected} for {s.study})')
        print('')

    def _get_suspicious(self) -> tuple[SuspiciousFeature]:
        return tuple(filter(self._focusing_on, self.suspicious))

    def _focusing_on(self, s: SuspiciousFeature) -> bool:
        if s.number_null >= self.minimum_null:
            return True
        if (s.number_null / s.total_expected) >= self.minimum_fraction_null:
            return True
        if (1 - (s.number_complete / s.total_expected)) >= self.fraction_missing:
            return True
        return False

    def _solicit_parameters(self) -> None:
        print('Minimum number of null values, to focus on [5]: ', end='')
        i = input()
        self.minimum_null = int(i) if i != '' else 5
        print('Minimum fraction of values being null values, to focus on [0.20]: ', end='')
        i = input()
        self.minimum_fraction_null = float(i) if i != '' else 0.20
        print('Fraction of missing values threshold, to focus on [0.10]: ', end='')
        i = input()
        self.fraction_missing = float(i) if i != '' else 0.10

    def _confirm_delete(self) -> None:
        c = len(self._get_suspicious())
        print(f'Delete these {c} features [y/n]? ', end='')
        i = input()
        if i != 'y':
            print('Cancelled.')
            sys_exit(0)

    def _do_delete(self) -> None:
        marked = self._get_suspicious()
        rows = list(map(lambda s: {'feature': s.feature, 'study': s.study}, marked))
        for study, group in DataFrame(rows).groupby('study'):
            print(study)
            with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
                for feature in group['feature']:
                    print(f'Deleting: {feature}')
                    InteractiveFeatureDropper.delete_feature(feature, cursor)
            print('')


@define
class InteractiveFeatureDropper:
    study: str
    database_config_file: str
    specification: str | None
    known_specifications: tuple[str, ...] | None = None
    specifiers: tuple[str, ...] | None = None
    method: str | None = None

    def start(self):
        specified = self._solicit_specification()
        if not specified:
            return
        proceed = self._solicit_confirmation()
        if not proceed:
            self._print('Cancelling by user request.', 'flag')
            return
        self._perform_deletion()

    def _solicit_specification(self) -> bool:
        specifications = self._get_specifications()
        if specifications is None:
            return False
        columns = ['Specification', 'Specifier', 'Ordinality', 'Method']
        df = DataFrame(specifications, columns=columns)
        self.known_specifications = tuple(df['Specification'])

        self._print(f'   Feature specifications for study "{self.study}"   ', 'title')
        for method, df1 in df.groupby('Method'):
            self._print(str(method), 'method')
            for specification, df2 in df1.groupby('Specification'):
                one_liner = self._form_one_liner(df2)
                self._print(str(specification).rjust(3), 'specification', end='')
                self._print(': ', None, end='')
                self._print(one_liner, 'specifiers')
            print('')

        if self.specification is not None:
            if not self._check_valid_specification():
                self._print('Specification ', 'message', end='')
                self._print(self.specification, 'specification', end='')
                self._print(' does not exist.', 'message')
                return False
        else:
            self._print('Choose specification: ', 'message', end='')
            try:
                self.specification = input()
                print()
            except KeyboardInterrupt:
                self._print('Cancelled by user request.', 'flag')
                return False
        if not self._check_valid_specification():
            self._print(self.specification, 'specification', end='')
            self._print(' is not a valid specification', 'message')
            return False

        _df = df[df['Specification'] == self.specification].copy()
        _df['Int ordinality'] = df['Ordinality'].apply(int)
        self.specifiers = tuple(_df.sort_values(by='Int ordinality')['Specifier'])
        self.method = str(tuple(_df['Method'])[0])
        return True

    def _print(self, message: str, style: str | None, end: str = '\n') -> None:
        codes = {
            None: '',
            'title': '\033[7;36m',
            'method': '\033[100;97m',
            'message': '',
            'specification': CustomFormatter.magenta,
            'specifiers': CustomFormatter.blue,
            'order': '\033[100;97m',
            'prompt': '',
            'flag': CustomFormatter.red,
            'no': CustomFormatter.red,
            'yes': CustomFormatter.green,
        }
        reset = CustomFormatter.reset
        print(f'{codes[style]}{message}{reset}', end=end)

    def _check_valid_specification(self) -> bool:
        if self.specification in cast(tuple[str, ...], self.known_specifications):
            return True
        return False

    def _form_one_liner(self, df: DataFrame) -> str:
        df['Int ordinality'] = df['Ordinality'].apply(int)
        df = df.sort_values(by='Int ordinality')
        specifiers = tuple(df['Specifier'])
        return ', '.join([str(s) for s in specifiers])

    def _solicit_confirmation(self) -> bool:
        self._announce_plan()
        self._print('Proceed? [', 'prompt', end='')
        self._print('y', 'yes', end='')
        self._print('/', 'prompt', end='')
        self._print('n', 'no', end='')
        self._print('] ', 'prompt', end='')
        answer = input()
        print()
        if answer in ('y', 'Y', 'yes'):
            return True
        return False

    def _announce_plan(self) -> None:
        self._print('Deleting specification ', 'message', end='')
        self._print(cast(str, self.specification), 'specification', end='')
        self._print(':', 'message')
        for i, specifier in enumerate(cast(tuple[str, ...], self.specifiers)):
            self._print(str(i + 1).rjust(8) + ' ', 'order', end='')
            self._print(' ', None, end='')
            self._print(specifier, 'specifiers')
        self._print('method'.rjust(8) + ' ', 'order', end='')
        self._print(' ', None, end='')
        method = cast(str, self.method)
        self._print(method[0:min(len(method), 100)] + ' ...', 'specifiers')

    def _perform_deletion(self):
        self._print('Proceed to delete specification ', 'message', end='')
        self._print(self.specification, 'specification', end='')
        self._print('.', 'message')
        with DBCursor(database_config_file=self.database_config_file, study=self.study) as cursor:
            self.delete_feature(self.specification, cursor)
        self._print('Done.', 'message')

    @staticmethod
    def delete_feature(feature: str | int, cursor) -> None:
        param = (feature,)
        cursor.execute('DELETE FROM quantitative_feature_value_queue WHERE feature=%s ;', param)
        cursor.execute('DELETE FROM quantitative_feature_value WHERE feature=%s ;', param)
        cursor.execute('DELETE FROM feature_specifier WHERE feature_specification=%s ;', param)
        cursor.execute('DELETE FROM feature_specification WHERE identifier=%s ;', param)
        cursor.execute('DELETE FROM feature_hash WHERE feature=%s ;', param)

    def _get_specifications(self) -> tuple[tuple[str, ...], ...] | None:
        with DBCursor(database_config_file=self.database_config_file, study=self.study) as cursor:
            cursor.execute('''
            SELECT fs.identifier, fsp.specifier, fsp.ordinality, fs.derivation_method
            FROM feature_specification fs
            JOIN feature_specifier fsp ON fsp.feature_specification=fs.identifier ;
            ''')
            rows = tuple(tuple(str(x) for x in row) for row in cursor.fetchall())
        if len(rows) == 0:
            self._print('No feature specification for study ', 'flag', end='')
            self._print(self.study, None)
            return None
        return rows


def main():
    args = parse_args()
    database_config_file = get_and_validate_database_config(args)
    study = args.study_name
    specification = args.specification
    if args.bulk_null:
        gui = BulkDropper(database_config_file)
    else:
        gui = InteractiveFeatureDropper(study, database_config_file, specification)
        gui.start()


if __name__=='__main__':
    main()
