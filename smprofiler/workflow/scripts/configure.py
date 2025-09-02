"""CLI utility to configure an SMProfiler workflow run."""
from typing import Literal
from typing import cast
import re
from argparse import ArgumentParser
from argparse import RawDescriptionHelpFormatter
from os import (
    getcwd,
    stat,
    chmod,
    makedirs,
)
from os import environ as os_environ
from os.path import (
    exists,
    join,
    abspath,
    expanduser,
)
from stat import S_IEXEC
from configparser import ConfigParser
from importlib.resources import as_file
from importlib.resources import files
from attr import define
from boto3 import client as boto3_client
from botocore.exceptions import ClientError

from smprofiler import __version__ as SMProfiler_VERSION


try:
    from jinja2 import Environment, BaseLoader
except ModuleNotFoundError as e:
    from smprofiler.standalone_utilities.module_load_error import \
        SuggestExtrasException
    SuggestExtrasException(e, 'workflow')
from jinja2 import Environment, BaseLoader  # pylint: disable=ungrouped-imports

from smprofiler.workflow.common.cli_arguments import add_argument  # pylint: disable=ungrouped-imports
from smprofiler import get_workflow
from smprofiler import get_workflow_names
from smprofiler.workflow.common.\
    file_identifier_schema import get_input_filename_by_identifier
from smprofiler.workflow.common.workflow_module_exporting import WorkflowModules
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger('smprofiler db configure')

NF_CONFIG_FILE = 'nextflow.config'


def _retrieve_from_library(subpackage: str, filename: str) -> str:
    filepath = files('.'.join(('smprofiler.workflow', subpackage))).joinpath(filename)
    with as_file(filepath) as path:
        with open(path, 'rt', encoding='utf-8') as file:
            contents = file.read()
    return contents


def _write_config_file(variables: dict[str, str]) -> None:
    contents = _retrieve_from_library('assets', NF_CONFIG_FILE + '.jinja')
    template = jinja_environment.from_string(contents)
    file_to_write = template.render(**variables)
    file_to_write = re.sub(r'\n\n+', '\n', file_to_write)
    with open(join(getcwd(), NF_CONFIG_FILE), 'wt', encoding='utf-8') as file:
        file.write(file_to_write)


def _write_pipeline_script(workflow: WorkflowModules) -> None:
    main_seen: bool = False
    for subpackage, filename, is_main in workflow.assets_needed:
        pipeline_file = _retrieve_from_library(subpackage, filename)
        if is_main:
            if main_seen:
                raise ValueError(
                    f'Workflow can only have one main Nextflow file. If it\'s {subpackage}.'
                    f'{filename}, check assets_needed to ensure that it\'s the only file with a '
                    'True value for the third element of the tuple.'
                )
            main_seen = True
            copy_location = join(getcwd(), 'main.nf')
        else:
            makedirs(join(getcwd(), 'nf_files'), exist_ok=True)
            copy_location = join(getcwd(), 'nf_files', filename)
        with open(copy_location, 'wt', encoding='utf-8') as file:
            file.write(pipeline_file)
    if not main_seen:
        raise ValueError('Workflow must have a main Nextflow file.')


def _record_configuration_command(variables: dict[str, str], configuration_file: str) -> None:
    tokens = ['smprofiler workflow configure']
    tokens.append(f"--workflow=\"{variables['workflow']}\"")
    configuration_file = abspath(configuration_file)
    if ' ' in configuration_file:
        configuration_file = f'"{configuration_file}"'
    tokens.append(f"--config-file=\"{configuration_file}\"")
    command = ' \\\n '.join(tokens)

    with open('configure.sh', 'wt', encoding='utf-8') as file:
        file.write('#!/bin/sh\n\n')
        file.write(command)
        file.write('\n')

    with open('run.sh', 'wt', encoding='utf-8') as file:
        file.write('#!/bin/sh\n\n')
        if 'input_path' in variables and _source_of_reference(variables['input_path']) == 's3':
            file.write('# Unsetting the below is a workaround for Nextflow\'s default non-support for session-specific credentials.\n')
            file.write('# This is intended to force Nextflow to fall back to ~/.aws/credentials, for which Nextflow DOES support\n')
            file.write('# session-specific credentials.\n')
            file.write('unset AWS_ACCESS_KEY_ID\n')
            file.write('unset AWS_SECRET_ACCESS_KEY\n\n')
        file.write('nextflow run .\n')

    file_stat = stat('configure.sh')
    chmod('configure.sh', file_stat.st_mode | S_IEXEC)
    file_stat = stat('run.sh')
    chmod('run.sh', file_stat.st_mode | S_IEXEC)


def _source_of_reference(path_or_uri: str) -> Literal['s3', 'local']:
    if re.search('^s3://', path_or_uri):
        return 's3'
    return 'local'


@define
class SMProfilerS3Resource:
    bucket: str
    dataset: str
    filename: str | None

    def is_directory(self) -> bool:
        return self.filename is None

    def get_key_string(self) -> str:
        if self.filename is not None:
            return '/'.join([self.dataset, self.filename])
        raise ValueError('This resource represents a directory, has no "Key" serialization.')


def _parse_s3_reference(uri: str) -> SMProfilerS3Resource:
    match = re.search(r'^s3://([\w\-]+)/([\w\-]+)/([\w\-\.]+)$', uri)
    if match:
        groups3 = cast(tuple[str, str, str], match.groups())
        return SMProfilerS3Resource(*groups3)
    else:
        match = re.search(r'^s3://([\w\-]+)/([\w\-]+)/?$', uri)
        if match:
            groups2 = cast(tuple[str, str], match.groups())
            return SMProfilerS3Resource(*groups2, None)
    raise ValueError(f'Could not parse uri "{uri}" as S3 resource for SMProfiler dataset.')


def _exists_s3_or_local(path_or_uri: str) -> bool:
    source = _source_of_reference(path_or_uri)
    if source == 's3':
        uri = path_or_uri
        resource = _parse_s3_reference(uri)
        client = boto3_client('s3')
        if resource.is_directory():
            listing = client.list_objects(Bucket=resource.bucket, Prefix=resource.dataset)
            return 'Contents' in listing
        else:
            try:
                client.head_object(Bucket=resource.bucket, Key=resource.get_key_string())
            except ClientError as error:
                if error.response['Error']['Code'] == '404':
                    return False
                raise ValueError('When checking file existence, got an unrelated access error.')
            return True
    if source == 'local':
        path = path_or_uri
        return exists(path)
    raise ValueError(f'Reference is neither a local path nor a URI: {path_or_uri}')


def _process_filename_inputs(options: dict[str, str | bool]) -> None:
    if not 'input_path' in options:
        return
    input_path = cast(str, options['input_path'])
    del options['input_path']
    if _exists_s3_or_local(input_path):
        file_manifest_path = join(input_path, 'file_manifest.tsv')
        if _exists_s3_or_local(file_manifest_path):
            options['input_path'] = input_path
            options['file_manifest_filename'] = file_manifest_path
        else:
            raise FileNotFoundError(file_manifest_path)
    else:
        if _source_of_reference(input_path) == 's3':
            resource = _parse_s3_reference(input_path)
            raise ValueError(f'\nS3 URI is wrong: {input_path}\nCheck the:\n  bucket:  "{resource.bucket}"\n  dataset: "{resource.dataset}"\n')
        raise FileNotFoundError(input_path)

    if _source_of_reference(file_manifest_path) == 's3':
        local_file_manifest = '_file_manifest.temp.tsv'
        resource = _parse_s3_reference(file_manifest_path)
        client = boto3_client('s3')
        client.download_file(resource.bucket, resource.get_key_string(), local_file_manifest)
    else:
        local_file_manifest = file_manifest_path

    samples_file = get_input_filename_by_identifier(
        input_file_identifier='Samples file',
        file_manifest_filename=local_file_manifest,
    )
    options['samples'] = False
    if not samples_file is None:
        samples_file_abs = join(input_path, samples_file)
        if _exists_s3_or_local(samples_file_abs):
            options['samples_file'] = samples_file_abs
            options['samples'] = True

    subjects_file = get_input_filename_by_identifier(
        input_file_identifier='Subjects file',
        file_manifest_filename=local_file_manifest,
    )
    options['subjects'] = False
    if not subjects_file is None:
        subjects_file_abs = join(input_path, subjects_file)
        if _exists_s3_or_local(subjects_file_abs):
            options['subjects_file'] = subjects_file_abs
            options['subjects'] = True

    study_file = get_input_filename_by_identifier(
        input_file_identifier='Study file',
        file_manifest_filename=local_file_manifest,
    )
    if not study_file is None:
        study_file_abs = join(input_path, study_file)
        if not _exists_s3_or_local(study_file_abs):
            raise FileNotFoundError(f'Did not find study file ({study_file}).')
        options['study_file'] = study_file_abs
        options['study'] = True

    diagnosis_file = get_input_filename_by_identifier(
        input_file_identifier='Diagnosis file',
        file_manifest_filename=local_file_manifest,
    )
    if not diagnosis_file is None:
        diagnosis_file_abs = join(input_path, diagnosis_file)
        if not _exists_s3_or_local(diagnosis_file_abs):
            raise FileNotFoundError(f'Did not find diagnosis file ({diagnosis_file}).')
        options['diagnosis_file'] = diagnosis_file_abs
        options['diagnosis'] = True

    interventions_file = get_input_filename_by_identifier(
        input_file_identifier='Interventions file',
        file_manifest_filename=local_file_manifest,
    )
    if not interventions_file is None:
        interventions_file_abs = join(input_path, interventions_file)
        if not _exists_s3_or_local(interventions_file_abs):
            raise FileNotFoundError(f'Did not find interventions file ({interventions_file}).')
        options['interventions_file'] = interventions_file_abs
        options['interventions'] = True

    channels_file = get_input_filename_by_identifier(
        input_file_identifier='Channels file',
        file_manifest_filename=local_file_manifest,
    )
    if not channels_file is None:
        channels_file_abs = join(input_path, channels_file)
        if not _exists_s3_or_local(channels_file_abs):
            raise FileNotFoundError(f'Did not find channels file ({channels_file}).')
        options['channels_file'] = channels_file_abs
        options['channels'] = True

    phenotypes_file = get_input_filename_by_identifier(
        input_file_identifier='Phenotypes file',
        file_manifest_filename=local_file_manifest,
    )
    if not phenotypes_file is None:
        phenotypes_file_abs = join(input_path, phenotypes_file)
        if not _exists_s3_or_local(phenotypes_file_abs):
            raise FileNotFoundError(f'Did not find phenotypes file ({phenotypes_file}).')
        options['phenotypes_file'] = phenotypes_file_abs
        options['phenotypes'] = True


def parse_arguments():
    """Process command line arguments."""
    parser = ArgumentParser(
        prog='smprofiler workflow configure',
        formatter_class=RawDescriptionHelpFormatter,
        description="""Configure an SMProfiler (smprofiler) run in the current directory.

Below the format of the workflow configuration file is described.

General variables should be included under:
    [general]:
    db_config_file: <path>
        Path to a database configuration file.
    container_platform: {None, docker, singularity} (default: None)
        Determines if processes are run locally or in a container and if so how.
    image_tag: <docker/singularity image name> (default: latest)
        Tag of the Docker Hub image associated with the workflow to use.

Some workflows require additional variables that are defined in their own section.
    [tabular import]:
    input_path: <path>
        Path to the directory containing the input data files like `file_manifest.tsv`. In
        some cases this can be an S3 URI.

    [graph generation]:
    graph_config_file: <path>
        Path to the graph configuration file. See smprofiler.graphs.config_reader for
        more details.

    [graph plugin]:
    plugin: {cg-gnn, graph-transformer}
        Which graph plugin to use.
    graph_config_file: <path>
        As above.
    cuda: {true, false} (default: false for cg-gnn, true for graph-transformer)
        Whether to use a CUDA-enabled container for the training step.
        Graph-transformer requires CUDA.
    upload_importances: {true, false} (default: false)
        Whether to upload feature importances to the database after training.
"""
    )
    add_argument(parser, 'workflow')
    parser.add_argument(
        '--config-file',
        help='Path to a workflow configuration file. This file will be used to populate the '
        'configuration file for the workflow.',
        required=True,
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_arguments()
    jinja_environment = Environment(loader=BaseLoader())

    config_variables: dict[str, str | bool | None] = {}
    config_file = ConfigParser()
    config_file.read(args.config_file)
    config_variables = dict(config_file.items('general')) if config_file.has_section('general') \
        else {}
    config_variables = {
        k: v.lower() if k not in ('db_config_file', 'input_path') else v
        for k, v in config_variables.items()
    }
    workflow_name: str = args.workflow.lower()
    workflows = {name: get_workflow(name) for name in get_workflow_names()}
    workflow_configuration = workflows[workflow_name]
    config_variables['workflow'] = args.workflow

    if 'db_config_file' not in config_variables:
        raise ValueError('db_config_file must be specified in the workflow configuration file.')
    arg = cast(str, config_variables['db_config_file'])
    if re.search('~', arg):
        db_config_file = expanduser(arg)
    else:
        db_config_file = arg
    if exists(db_config_file):
        config_variables['db_config_file'] = db_config_file
        config_variables['db_config'] = True
    else:
        logger.warning('Database configuration file was not found at the indicated location.')
        logger.debug('database_config_file: %s', config_variables['db_config_file'])
        logger.debug('db_config_file: %s', db_config_file)

    if ('container_platform' not in config_variables) or \
            (config_variables['container_platform'] == 'none'):
        config_variables['container_platform'] = None
    elif config_variables['container_platform'] not in {'docker', 'singularity'}:
        raise ValueError('container_platform must be one of "none", "docker", or "singularity". '
                         f'Got {config_variables["container_platform"]}')

    if ('image_tag' not in config_variables) or (config_variables['image_tag'] == ''):
        config_variables['image_tag'] = SMProfiler_VERSION
    config_variables['image'] = f'{workflow_configuration.image}:{config_variables["image_tag"]}'

    config_variables['current_working_directory'] = getcwd()

    if config_file.has_section(workflow_name):
        config_state = config_variables.copy()
        workflow_config_variables = dict(config_file.items(workflow_name))
        workflow_config_variables = {
            k: v.lower() if k != 'input_path' else v
            for k, v in workflow_config_variables.items()
        }
        config_state.update(workflow_config_variables)
        workflow_configuration.process_inputs(config_state)
        config_variables.update(config_state)
    elif workflow_configuration.config_section_required:
        raise ValueError(f'Workflow {workflow_name} requires a configuration section.')

    if workflow_name == 'tabular import':
        _process_filename_inputs(config_variables)
        if _source_of_reference(config_variables['input_path']) == 's3':
            def copy_profile_from_saml_to_default():
                if 'AWS_PROFILE'  in os_environ:
                    profile = os_environ['AWS_PROFILE']
                elif 'SAML2AWS_PROFILE' in os_environ:
                    profile = os_environ['SAML2AWS_PROFILE']
                else:
                    print('Warning: No AWS profile could be determined, implicitly using "default".')
                    return
                config = ConfigParser()
                filename = expanduser('~/.aws/credentials')
                config.read(filename)
                config['default'] = config[profile]
                with open(filename, 'wt', encoding='utf-8') as file:
                    config.write(file)
                print(f'Note: Overwrote "default" profile in ~/.aws/credentials with "{profile}" values.')
            copy_profile_from_saml_to_default()

    _write_config_file(config_variables)
    _write_pipeline_script(workflow_configuration)
    _record_configuration_command(config_variables, args.config_file)
