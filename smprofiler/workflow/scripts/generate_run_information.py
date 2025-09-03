"""CLI entry point into the "job generator" component of a given Nextflow-managed workflow.
This component creates a manifest of the parallelizable jobs for Nextflow to run.
"""

import argparse
from os.path import exists

from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler import get_workflow_names
from smprofiler import get_workflow

try:
    workflows = {name: get_workflow(name) for name in get_workflow_names()}
except ModuleNotFoundError as e:
    from smprofiler.standalone_utilities.module_load_error import \
        SuggestExtrasException
    SuggestExtrasException(e, 'workflow')
workflows = {name: get_workflow(name) for name in get_workflow_names()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow generate-run-information',
        description='''
        Create a list of core, parallelizable job specifications for a given SMProfiler
        workflow, as well as lists of file dependencies.
        
        Note: Due to orchestration design constraints, if this script must
        depend on file contents, it can *only* depend on the contents of explicitly
        indicated files. That is, it cannot "bootstrap" and open files whose names
        are discovered by reading other files' contents.
        ''',
    )
    add_argument(parser, 'workflow')
    add_argument(parser, 'database config')
    add_argument(parser, 'file manifest')
    parser.add_argument(
        '--input-path',
        dest='input_path',
        type=str,
        required=False,
        help='''Path to directory containing input data files. (For example,
        containing file_manifest.tsv).
        ''',
    )
    add_argument(parser, 'samples file')
    parser.add_argument(
        '--job-specification-table',
        dest='job_specification_table',
        type=str,
        required=True,
        help='Filename for output, job specification table CSV.',
    )
    add_argument(parser, 'study name')
    add_argument(parser, 'channels file')
    add_argument(parser, 'phenotypes file')
    parser.add_argument(
        '--use-file-based-data-model',
        dest='use_file_based_data_model',
        required=False,
        action='store_true',
        help='If set, will rely on files as dataset input.',
    )
    args = parser.parse_args()
    if args.use_file_based_data_model:
        if not exists(args.file_manifest_file):
            raise FileNotFoundError(args.file_manifest_file)

    Generator = workflows[args.workflow].generator
    if args.use_file_based_data_model:
        job_generator = Generator(
            file_manifest_file=args.file_manifest_file,
            input_path=args.input_path,
        )
    else:
        job_generator = Generator(
            study_name=args.study_name,
            database_config_file=args.database_config_file,
        )
    job_generator.write_job_specification_table(args.job_specification_table)
