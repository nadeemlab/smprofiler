import re
import json
from os import chdir
from os import mkdir
from os import environ as os_environ
from os.path import exists
from os.path import expanduser
from argparse import ArgumentParser

from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.pdf_generator import PDFReportGenerator
from smprofiler.workflow.automated_analysis.pdf_server import PDFReportServer
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.db.credentials import retrieve_credentials_from_file

def result_quality(r: Result) -> float:
    return -1 * r.quality()

if __name__=='__main__':
    parser = ArgumentParser(
        prog='smprofiler workflow automated-analysis',
        description='Perform basic automated multi-feature comparison analysis on one or several datasets.'
    )
    parser.add_argument('--database-config-file', required=True)
    parser.add_argument('--api-hostname', required=True)
    parser.add_argument('--analysis-options-json', required=True, help='''
List of items with: study "handle", and optionally "omitted_cohorts",
"omitted_channels", and "omit_proximity" (i.e. skip doing proximity
metric comparisons, for performance).''')
    args = parser.parse_args()

    dbc = args.database_config_file
    api_host = args.api_hostname
    options_file = args.analysis_options_json

    credentials = retrieve_credentials_from_file(expanduser(dbc))
    os_environ['SINGLE_CELL_DATABASE_HOST'] = credentials.endpoint
    os_environ['SINGLE_CELL_DATABASE_USER'] = credentials.user
    os_environ['SINGLE_CELL_DATABASE_PASSWORD'] = credentials.password
    studies = json.loads(open(options_file, 'rt', encoding='utf-8').read())
    for entry in studies:
        study = entry['handle']
        print('Doing ' + study + '.')
        omitted_cohorts = entry['omitted_cohorts']
        context = (api_host, dbc, study)
        sanitized, _ = StudyCollectionNaming.strip_token(study)
        sanitized = re.sub(' ', '_', sanitized.lower())
        subdir = sanitized
        if not exists(subdir):
            mkdir(subdir)
        chdir(subdir)
        oc = 'omitted_channels'
        omitted_channels = entry[oc] if oc in entry else None
        omit_proximity = entry['omit_proximity'] if 'omit_proximity' in entry else False
        generator = PDFReportGenerator(*context, omitted_cohorts=omitted_cohorts, omitted_channels=omitted_channels, omit_proximity=omit_proximity)
        generator.generate_and_save()
        server = PDFReportServer(*context[1:])
        pdf = server.datestamp_and_retrieve()
        open('analysis_summary_dated.pdf', 'wb').write(pdf)
        print(f'{subdir}/analysis_summary_dated.pdf written.')
        chdir('..')

