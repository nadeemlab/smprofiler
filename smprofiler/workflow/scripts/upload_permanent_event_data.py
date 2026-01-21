from os.path import join
from argparse import ArgumentParser

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.workflow.common.cli_arguments import add_argument
from smprofiler.workflow.tabular_import.parsing.permanent_event import get_permanent_events_transcriber

if __name__=='__main__':
    parser = ArgumentParser(
        prog='smprofiler workflow upload-permanent-event-data',
        description='Uploads permanent_condition_diagnosis and condition_lack records, and diagnosis records representing survival-type data.',
    )
    parser.add_argument('--generated-artifacts-path', help='Directory with generated file artifacts for dataset.')
    add_argument(parser, 'database config')
    args = parser.parse_args()
    file_path = args.generated_artifacts_path
    dbc = args.database_config_file
    study_file = join(file_path, 'study.json')
    study_name = StudyCollectionNaming.extract_study_from_file(study_file)
    with DBConnection(database_config_file=dbc, study=study_name) as connection:
        get_permanent_events_transcriber(file_path, connection).transcribe()


