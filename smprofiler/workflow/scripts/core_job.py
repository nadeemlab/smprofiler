"""CLI entry point into the core/parallelizable phase of the Nextflow-managed workflows."""
import argparse

from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler import get_workflow_names
from smprofiler import get_workflow
from smprofiler import get_core_job
workflows = {name: get_workflow(name) for name in get_workflow_names()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow core-job',
        description='One parallelizable "core" computation job.',
    )

    add_argument(parser, 'workflow')
    add_argument(parser, 'study name')
    add_argument(parser, 'database config')
    add_argument(parser, 'performance report file')
    add_argument(parser, 'results file')
    add_argument(parser, 'job index')
    add_argument(parser, 'source file identifier')
    add_argument(parser, 'source file name')
    add_argument(parser, 'channels file')
    add_argument(parser, 'phenotypes file')
    add_argument(parser, 'sample')

    parameters = vars(parser.parse_args())
    core_job = get_core_job(**parameters)
    core_job.calculate()
