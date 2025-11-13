
import re
from re import Match
from typing import cast
from urllib.parse import quote_plus as qp

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.workflow.automated_analysis.types import ReportableCase
from smprofiler.workflow.automated_analysis.types import Result

def latex_escape_url(url: str) -> str:
    def replacer(m: Match) -> str:
        return '\\' + m.group(1)
    return re.sub(r'([%_#&])', replacer, url)

def form_url(result: Result, study_name: str) -> str:
    base = 'https://smprofiler.io'
    study_sc = re.sub(' ', '-', study_name)
    cohorts = ','.join([result.higher_cohort, result.lower_cohort])
    def stringify(p: PhenotypeCriteria) -> str:
        return cast(str, ReportableCase._form_phenotype_str(p, special_cases=False))
    if result.case.other is not None:
        strings = [stringify(result.case.phenotype), stringify(result.case.other)]
    else:
        strings = [stringify(result.case.phenotype)]
    ps = ','.join(strings)
    if result.case.metric == 'proximity':
        phenotypes = ps
        composite = '&'.join(strings)
        selected_phenotypes = composite
        enrichfields = composite
        selected_enrichment = ', '.join(strings) + '_proximity'
        spatial = composite + '-proximity'
        path = f'study/{qp(study_sc)}/analysis/detail?cohorts={qp(cohorts)}&phenotypes={qp(phenotypes)}&selected_phenotypes={qp(selected_phenotypes)}&enrichfields={qp(enrichfields)}&selected_enrichment={qp(selected_enrichment)}&spatial={qp(spatial)}'
    else:
        phenotypes = ps
        columns = ps
        selected_phenotypes = ps
        path = f'study/{qp(study_sc)}/analysis/detail?cohorts={qp(cohorts)}&phenotypes={qp(phenotypes)}&columns={qp(columns)}&selected_phenotypes={qp(selected_phenotypes)}'
    return latex_escape_url(f'{base}/{path}')


