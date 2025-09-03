"""CLI entry point into the wrap-up/integration phase of the Nextflow-managed workflows."""
import argparse

from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler import get_integrator

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow aggregate-core-results',
        description='''
        Merge the results provided by all core jobs.
        ''',
    )
    parser.add_argument('core_computation_results_files', nargs='*', type=str)
    add_argument(parser, 'workflow')
    add_argument(parser, 'database config')
    add_argument(parser, 'study name')
    add_argument(parser, 'channels file')
    add_argument(parser, 'phenotypes file')

    args = vars(parser.parse_args())

    integrator = get_integrator(**args)
    integrator.calculate(**args)
