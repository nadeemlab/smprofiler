from argparse import ArgumentParser

from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler.workflow.tabular_import.parsing.permanent_event import transcribe_permanent_event_metadata

if __name__=='__main__':
    parser = ArgumentParser(
        prog='smprofiler workflow upload-permanent-event-data',
        description='Uploads permanent_condition_diagnosis and condition_lack records, and diagnosis records representing survival-type data.',
    )
    add_argument(parser, 'database config')
    args = parser.parse_args()
    dbc = args.databse_config_file

