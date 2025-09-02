"""A utility to install bash completions for `smprofiler`."""
from importlib.resources import as_file
from importlib.resources import files
from os.path import expanduser
from os.path import join
from os.path import exists
import argparse
import sys

from jinja2 import Environment
from jinja2 import BaseLoader

from smprofiler.entry_point.cli import get_commands
from smprofiler import submodule_names

HEADER = '### Start added by smprofiler'
FOOTER = '### End added by smprofiler'


def remove_previous_installation(filename):
    with open(filename, 'rt', encoding='utf-8') as file:
        contents = file.read()
    header_index = None
    footer_index = None
    try:
        header_index = contents.index(HEADER)
    except ValueError:
        pass
    try:
        footer_index = contents.index(FOOTER)
    except ValueError:
        pass
    if (not header_index is None) and (not footer_index is None):
        start_point = header_index - 1
        end_point = footer_index + len(FOOTER) + 1
        new_contents = contents[0:start_point] + contents[end_point:]
        with open(filename, 'wt', encoding='utf-8') as file:
            file.write(new_contents)
            print(f'Removed previous completion code from {filename}')


def get_nontrivial_module_names():
    return [name for name in submodule_names if len(get_commands(name)) > 0]


def get_modules_and_commands():
    return [
        {
            'name': module_name,
            'command_names_joined_space': ' '.join(get_commands(module_name)),
            'command_names_joined_bar': '|'.join([f"'{c}'" for c in get_commands(module_name)]),
        }
        for module_name in get_nontrivial_module_names()
    ]


def create_completions_script():
    jinja_environment = Environment(loader=BaseLoader(), comment_start_string='###')
    filepath = files('smprofiler.entry_point').joinpath('smprofiler-completion.sh.jinja')
    with as_file(filepath) as path:
        with open(path, 'r', encoding='utf-8') as file:
            template_source = file.read().rstrip('\n')
    template = jinja_environment.from_string(template_source)
    modules = get_modules_and_commands()
    return template.render(
        module_names=' '.join(get_nontrivial_module_names()), modules=modules)


def attempt_append_to(filename, contents):
    if exists(filename):
        remove_previous_installation(filename)
        with open(filename, 'a', encoding='utf-8') as file:
            file.write(contents)
        print(f'Wrote completions script fragment to:\n {filename}')
        print('Either open a new shell or do:')
        print(f'    source {filename}')
        sys.exit()


def main_program():
    parser = argparse.ArgumentParser(
        prog='smprofiler-enable-completion',
        description='Enable/disable tab completion for smprofiler commands.',
    )
    parser.add_argument(
        '--disable',
        dest='disable',
        action='store_true',
        help='Disable completions, i.e. uninstall the bash complete snippet from profile '
        'configuration files.'
    )
    parser.add_argument(
        '--script-file',
        dest='script_file',
        help='If provided, this filename will be used in place of a user profile file. '
        'For testing/inspection.'
    )
    args = parser.parse_args()

    if args.script_file:
        profile_files = [args.script_file]
    else:
        profile_files = [join(expanduser('~'), f) for f in ['.bash_profile', '.bashrc', '.profile']]
    if args.disable:
        for path in profile_files:
            if exists(path):
                remove_previous_installation(path)
        sys.exit()

    completion_script = create_completions_script()
    wrapped = f'\n{HEADER}\n{completion_script}\n{FOOTER}\n'

    for path in profile_files:
        attempt_append_to(path, wrapped)
