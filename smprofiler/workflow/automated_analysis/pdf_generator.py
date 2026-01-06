from os import system as os_system
from os.path import exists
from json import loads as json_loads
from json import dumps as json_dumps
from typing import cast

from cattrs import Converter
from pandas import DataFrame
import seaborn as sns
import matplotlib.pyplot as plt
from jinja2 import BaseLoader
from jinja2 import Environment

from smprofiler.workflow.scripts.configure import _retrieve_from_library
from smprofiler.db.http_data_accessor import StudyDataAccessor
from smprofiler.standalone_utilities.timestamping import now
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.workflow.automated_analysis.assessment_logger import AssessmentLogger
from smprofiler.workflow.automated_analysis.auto_assessor import StudyAutoAssessor
from smprofiler.workflow.automated_analysis.types import Highlights
from smprofiler.workflow.automated_analysis.urls import latex_escape_url
from smprofiler.db.database_connection import DBCursor
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

def _pydantic_adaptor(value: PhenotypeCriteria) -> dict[str, tuple[str, ...]]:
    if isinstance(value, PhenotypeCriteria):
        return {'positive_markers': value.positive_markers, 'negative_markers': value.negative_markers}

def _pandas_adaptor(_: DataFrame) -> str:
    return '(elided)'


class PDFReportGenerator:
    """
    Performs automated multi-feature analysis of one study and
    generates a single document overview report.
    """
    api_host: str
    database_config_file: str
    study: str
    omitted_cohorts: list[str] | None
    omitted_channels: list[str] | None
    parameters: dict
    pdf: bytes

    def __init__(self, api_host: str, database_config_file: str, study: str, omitted_cohorts: list[str] | None, omitted_channels: list[str] | None):
        self.api_host = api_host
        self.database_config_file = database_config_file
        self.study = study
        self.omitted_cohorts = omitted_cohorts
        self.omitted_channels = omitted_channels

    def generate_and_save(self) -> None:
        self._generate_template_parameters()
        self._fill_report_template()
        self._save_pdf_to_database()

    def _generate_template_parameters(self) -> None:
        cache_file = 'template_parameters.json'
        if exists(cache_file):
            self.parameters = json_loads(open(cache_file, 'rt', encoding='utf-8').read())
            logger.debug(f'Retrieved {cache_file}')
            return
        with StudyAutoAssessor(
            StudyDataAccessor(
                self.study,
                host=self.api_host,
                use_session=True,
                database_config_file=self.database_config_file,
                bypass_api=True,
                use_readonly_bulk_feature_cache=True,
            ),
            omitted_cohorts=self.omitted_cohorts,
            omitted_channels=self.omitted_channels,
        ) as a:
            summary = a.get_summary()
        self._generate_kde_plot(summary.results.dataframe, summary.highlights)
        cattrs_converter = Converter()
        cattrs_converter.register_unstructure_hook(PhenotypeCriteria, _pydantic_adaptor)
        cattrs_converter.register_unstructure_hook(DataFrame, _pandas_adaptor)
        self.parameters = cattrs_converter.unstructure(summary) 
        with open(cache_file, 'wt', encoding='utf-8') as file:
            file.write(json_dumps(self.parameters, indent=2))
        logger.debug(f'Wrote {cache_file}')

    def _generate_kde_plot(self, df: DataFrame, highlights: Highlights) -> None:
        logger.debug(df.columns)
        label = 'Quality score'
        df = df.rename(columns={'quality': label})
        sns.set_theme(rc={'figure.figsize':(8, 3)})
        plt.figure()
        sns.histplot(df, x=label, kde=True, bins=15, stat='percent')
        for i, r in enumerate(highlights.top3):
            plt.text(r.base.significance.quality(), 20, s=f'{i+1}', color='#a0119e')
        plt.savefig('kde.pdf', bbox_inches='tight')
        plt.close()

    def _fill_report_template(self) -> None:
        jinja_environment = Environment(loader=BaseLoader(), comment_start_string='###')
        jinja_environment.filters['pvalue_filter'] = AssessmentLogger._format_p
        jinja_environment.filters['effect_filter'] = AssessmentLogger._format_effect
        jinja_environment.filters['quality_filter'] = AssessmentLogger._format_quality_score
        jinja_environment.filters['latex_escape_url'] = latex_escape_url
        contents = cast(str, _retrieve_from_library('assets', 'analysis_summary.tex.jinja'))
        template = jinja_environment.from_string(contents)
        rendered = template.render(**self.parameters)
        logger.debug('Finished rendering with Jinja.')
        with open('analysis_summary.tex', 'wt', encoding='utf-8') as file:
            file.write(rendered)
        for filename in ('blue_tile.pdf', 'fractions.pdf', 'ratios.pdf', 'proximity.pdf', 'smprofiler_logo.pdf', 'link-out.pdf'):
            file_contents = cast(bytes, _retrieve_from_library('assets', filename, binary=True))
            with open(filename, 'wb') as file:
                file.write(file_contents)
        logfile = 'report_generation.log'
        os_system(f'pdflatex analysis_summary.tex --interaction=nonstopmode > {logfile}')
        os_system(f'pdflatex analysis_summary.tex --interaction=nonstopmode > {logfile}')
        logger.debug('report_generation.log written (pdflatex runs)')
        self.pdf = open('analysis_summary.pdf', 'rb').read()

    def _save_pdf_to_database(self) -> None:
        logger.debug('Writing generated PDF to database.')
        with DBCursor(database_config_file=self.database_config_file, study=self.study) as cursor:
            create = '''
            CREATE TABLE IF NOT EXISTS pdf_reports ( blob bytea, date_generated timestamptz );
            '''
            insert = '''
            INSERT INTO pdf_reports VALUES (%s, %s) ;
            '''
            cursor.execute(create)
            cursor.execute(insert, (self.pdf, now()))
        logger.debug('Done writing.')


