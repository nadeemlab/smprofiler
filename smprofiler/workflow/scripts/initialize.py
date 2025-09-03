"""Invoker of the initialize phase of a Nextflow-managed workflow."""
import argparse

from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler import get_initializer

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow initialize',
        description='A job that runs before all the main (parallelizable) jobs.',
    )

    add_argument(parser, 'study name')
    add_argument(parser, 'file manifest')
    add_argument(parser, 'study file')
    add_argument(parser, 'database config')
    add_argument(parser, 'channels file')
    add_argument(parser, 'phenotypes file')
    add_argument(parser, 'samples file')
    add_argument(parser, 'subjects file')
    add_argument(parser, 'diagnosis file')
    add_argument(parser, 'interventions file')
    add_argument(parser, 'workflow')

    parameters = vars(parser.parse_args())

    initializer = get_initializer(**parameters)
    initializer.initialize(**parameters)
