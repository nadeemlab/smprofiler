import re
import json
from os import chdir
from os import mkdir
from os.path import exists
from os import environ as os_environ
import sys

from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.pdf_generator import PDFReportGenerator
from smprofiler.workflow.automated_analysis.pdf_server import PDFReportServer
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.db.credentials import retrieve_credentials_from_file

def result_quality(r: Result) -> float:
    return -1 * r.quality()

if __name__=='__main__':
    dbc = sys.argv[1]
    api_host = sys.argv[2]
    credentials = retrieve_credentials_from_file(dbc)
    os_environ['SINGLE_CELL_DATABASE_HOST'] = credentials.endpoint
    os_environ['SINGLE_CELL_DATABASE_USER'] = credentials.user
    os_environ['SINGLE_CELL_DATABASE_PASSWORD'] = credentials.password
    studies = json.loads(open('study_names.json', 'rt', encoding='utf-8').read())
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
        generator = PDFReportGenerator(*context, omitted_cohorts=omitted_cohorts)
        generator.generate_and_save()
        server = PDFReportServer(*context[1:])
        pdf = server.datestamp_and_retrieve()
        open('analysis_summary_dated.pdf', 'wb').write(pdf)
        print(f'{subdir}/analysis_summary_dated.pdf written.')
        chdir('..')

