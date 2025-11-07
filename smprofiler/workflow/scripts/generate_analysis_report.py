from argparse import ArgumentParser

from smprofiler.standalone_utilities.log_formats import colorized_logger

from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.pdf_generator import PDFReportGenerator
from smprofiler.workflow.automated_analysis.pdf_server import PDFReportServer

logger = colorized_logger(__name__)

def result_quality(r: Result) -> float:
    return -1 * r.quality()

if __name__=='__main__':
    p = ArgumentParser(prog='survey', description='Automated basic analysis and report generation.')
    p.add_argument('study')
    p.add_argument('--database-config-file', type=str, required=True)
    p.add_argument('--api-server', type=str, required=True)
    p.add_argument('--omitted-cohorts', type=str, required=False)
    args = vars(p.parse_args())
    study = args['study']
    if args['omitted_cohorts']:
        omitted_cohorts = args['omitted_cohorts'].split(',')
    else:
        omitted_cohorts = None
    context = (args['api_server'], args['database_config_file'],args['study'])
    generator = PDFReportGenerator(*context, omitted_cohorts=omitted_cohorts)
    generator.generate_and_save()
    server = PDFReportServer(*context[1:])
    pdf = server.datestamp_and_retrieve()
    open('analysis_summary_dated.pdf', 'wb').write(pdf)
    print('analysis_summary_dated.pdf written.')


