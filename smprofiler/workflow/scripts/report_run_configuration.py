"""CLI entry point into the utility that reports (for informational purposess or debugging) the
configuration of a Nextflow-managed workflow before it runs.
"""

import argparse

try:
    from smprofiler.workflow.common.logging.run_configuration_reporter import \
        RunConfigurationReporter
except ModuleNotFoundError as e:
    from smprofiler.standalone_utilities.module_load_error import \
        SuggestExtrasException
    SuggestExtrasException(e, 'workflow')
from smprofiler.workflow.common.logging.run_configuration_reporter import \
    RunConfigurationReporter
from smprofiler.workflow.common.cli_arguments import add_argument


def main():
    parser = argparse.ArgumentParser(
        prog='smprofiler workflow report-run-configuration',
        description='''Log information about an SMProfiler run configuration.'''
    )
    add_argument(parser, 'workflow')
    add_argument(parser, 'file manifest')
    add_argument(parser, 'samples file')
    add_argument(parser, 'channels file')
    add_argument(parser, 'phenotypes file')
    args = parser.parse_args()

    data_files = {
        name: vars(args)['_'.join([name, 'file'])]
        if '_'.join([name, 'file']) in vars(args) else None
        for name in ['samples', 'channels', 'phenotypes']
    }
    args_dict = vars(args)
    for name in ['samples', 'channels', 'phenotypes']:
        key = '_'.join([name, 'file'])
        if key in args_dict:
            del args_dict[key]
    RunConfigurationReporter(**args_dict, data_files=data_files)


if __name__ == '__main__':
    main()
