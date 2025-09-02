"""CLI arguments solicitation."""
import re
from typing import Literal
from typing import Union
from typing import get_args
from typing import cast
from argparse import ArgumentParser

from smprofiler import get_workflow_names


SettingArgumentName = Literal['workflow', 'source file identifier', 'source file name', 'sample',
                              'database config', 'file manifest', 'study name',
                              'job index']
FileArgumentName = Literal['phenotypes file', 'channels file', 'study file', 'samples file',
                           'subjects file', 'diagnosis file', 'interventions file',
                           'performance report file', 'results file']


def add_argument(parser: ArgumentParser, name: Union[SettingArgumentName, FileArgumentName]):
    if name in get_args(FileArgumentName):
        add_file_argument(parser, cast(FileArgumentName, name))

    if name == 'workflow':
        parser.add_argument('--workflow', dest='workflow', choices=get_workflow_names(),
                            required=True)
    if name == 'source file identifier':
        parser.add_argument('--input-file-identifier', dest='input_file_identifier', type=str,
                            required=False,
                            help='An input file identifier, as it appears in the file manifest.')
    if name == 'source file name':
        parser.add_argument('--input-filename', dest='input_filename', type=str, required=False)
    if name == 'sample':
        parser.add_argument('--sample-identifier', dest='sample_identifier', type=str,
                            required=False,
                            help='The sample identifier associated with the given input file, as '
                            'it appears in the file manifest.')
    if name == 'database config':
        parser.add_argument('--database-config-file', dest='database_config_file', type=str,
                            help='Provide the file for database configuration.')
    if name == 'file manifest':
        parser.add_argument('--file-manifest-file', dest='file_manifest_file', type=str,
                            required=False)
    if name == 'study name':
        parser.add_argument('--study-name', dest='study_name', type=str, required=False,
                            help='The name of the study/dataset to do the workflow computation'
                                 ' over.')
    if name == 'job index':
        parser.add_argument('--job-index', dest='job_index', type=str, required=False)


def add_file_argument(parser, name: FileArgumentName):
    hyphens = re.sub(' ', '-', name)
    snake = re.sub(' ', '_', name)
    parser.add_argument(f'--{hyphens}', dest=f'{snake}', type=str, required=False)
