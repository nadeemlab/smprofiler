from os.path import exists
from argparse import ArgumentParser

from smprofiler.standalone_utilities.log_formats import colorized_logger

from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.pdf_generator import PDFReportGenerator
from smprofiler.workflow.automated_analysis.pdf_server import PDFReportServer

logger = colorized_logger(__name__)

def result_quality(r: Result) -> float:
    return -1 * r.quality()

def get_default_host(given: str | None) -> str | None:
    if given is not None:
        return given
    filename = 'api_host.txt'
    if exists(filename):
        with open(filename, 'rt', encoding='utf-8') as file:
            host = file.read().rstrip()
    else:
        host = None
    return host

if __name__=='__main__':
    p = ArgumentParser(prog='survey', description='Automated basic analysis.')
    p.add_argument('study')
    p.add_argument('--database-config-file', type=str, required=True)
    p.add_argument('--omitted-cohorts', type=str, required=False)
    args = vars(p.parse_args())
    study = args['study']
    if args['omitted_cohorts']:
        omitted_cohorts = args['omitted_cohorts'].split(',')
    else:
        omitted_cohorts = None
    host = get_default_host(None)
    if host is None:
        raise RuntimeError('Could not determine API server hostname.')
    context = (args['database_config_file'], args['study'])
    generator = PDFReportGenerator(host, *context, omitted_cohorts=omitted_cohorts)
    generator.generate_and_save()
    server = PDFReportServer(*context)
    pdf = server.datestamp_and_retrieve()
    open('analysis_summary_dated.pdf', 'wb').write(pdf)
    print('analysis_summary_dated.pdf written.')




