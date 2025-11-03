from os.path import exists
from os import system as os_system
from argparse import ArgumentParser
from json import dumps as json_dumps

from cattrs import Converter
from pandas import DataFrame
from jinja2 import BaseLoader
from jinja2 import Environment

from smprofiler.workflow.scripts.configure import _retrieve_from_library
from smprofiler.db.http_data_accessor import StudyDataAccessor
from smprofiler.standalone_utilities.log_formats import colorized_logger

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.workflow.automated_analysis.limits import LIMITS_SEVERE
from smprofiler.workflow.automated_analysis.types import FilteredResults
from smprofiler.workflow.automated_analysis.types import Highlights
from smprofiler.workflow.automated_analysis.assessment_logger import AssessmentLogger
from smprofiler.workflow.automated_analysis.auto_assessor import StudyAutoAssessor

logger = colorized_logger(__name__)

def _pydantic_adaptor(value: PhenotypeCriteria) -> dict[str, tuple[str, ...]]:
    if isinstance(value, PhenotypeCriteria):
        return {'positive_markers': value.positive_markers, 'negative_markers': value.negative_markers}

def _pandas_adaptor(_: DataFrame) -> str:
    return '(elided)'

cattrs_converter = Converter()
cattrs_converter.register_unstructure_hook(PhenotypeCriteria, _pydantic_adaptor)
cattrs_converter.register_unstructure_hook(DataFrame, _pandas_adaptor)

def result_quality(r: Result) -> float:
    return -1 * r.quality()
 
def print_to_console_3_metric_types(results: FilteredResults, assessment_logger: AssessmentLogger) -> None:
    print('')
    print('Single channel fractions results:')
    for result in sorted(results.single_fractions, key=result_quality):
        print(assessment_logger._format_singleton(result))
    print('')

    print('Ratio of channels fractions results:')
    for result in sorted(results.ratios, key=result_quality):
        print(assessment_logger._format_ratio(result))
    print('')

    print('Proximity results:')
    for result in sorted(results.proximity, key=result_quality):
        if LIMITS_SEVERE.acceptable(result.significance):
            print(assessment_logger._format_proximity(result))

def print_to_console(results, highlights, assessment_logger) -> None:
    print_to_console_3_metric_types(results, assessment_logger)
    print('')
    print('Top 3 from filtered:')
    for result in sorted(highlights.top3, key=result_quality):
        print(assessment_logger._format_singleton(result))
    print('')
    print('Top 25s, after accounting for patterns:')
    print_to_console_3_metric_types(highlights.top10, assessment_logger)

def generate_report(summary) -> None:
    jinja_environment = Environment(loader=BaseLoader(), comment_start_string='###')
    jinja_environment.filters['pvalue_filter'] = AssessmentLogger._format_p
    jinja_environment.filters['effect_filter'] = AssessmentLogger._format_effect
    contents = _retrieve_from_library('assets', 'analysis_summary.tex.jinja')
    template = jinja_environment.from_string(contents)
    rendered = template.render(**summary)
    with open('analysis_summary.tex', 'wt', encoding='utf-8') as file:
        file.write(rendered)
    os_system('pdflatex analysis_summary.tex')

def survey(host: str, study: str, interactive: bool, omitted_cohorts: list[str] | None) -> tuple[FilteredResults, Highlights]:
    with StudyAutoAssessor(StudyDataAccessor(study, host=host), interactive=interactive, omitted_cohorts=omitted_cohorts) as a:
        summary = a.get_filtered_results()
        assessment_logger = a.logger
    print_to_console(summary.results, summary.highlights, assessment_logger)
    plain_structured = cattrs_converter.unstructure_attrs_asdict(summary) 
    print(json_dumps(plain_structured, indent=2))
    generate_report(plain_structured)
    return summary.results, summary.highlights

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
    df = survey(host, study, True, omitted_cohorts=omitted_cohorts)

