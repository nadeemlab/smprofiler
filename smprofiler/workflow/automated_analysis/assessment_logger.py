from decimal import Decimal

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.standalone_utilities.terminal_scrolling import TerminalScrollingBuffer
from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource
from smprofiler.workflow.automated_analysis.types import Result
from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger(__name__)

class AssessmentLogger(ChainableDestructableResource):
    interactive: bool
    buffer: TerminalScrollingBuffer
    name_width: int

    def __init__(self, interactive: bool=True, scrolling_buffer_lines: int=20):
        self.interactive = interactive
        if interactive:
            self.buffer = TerminalScrollingBuffer(scrolling_buffer_lines)
            self.add_subresource(self.buffer)

    def set_name_width(self, w: int) -> None:
        self.name_width = w

    def log(self, message: str, **kwargs) -> None:
        if self.interactive:
            self.buffer.add_line(message, **kwargs)
        else:
            logger.info(message)

    def log_singleton(self, result: Result, _: tuple[Result, ...]) -> None:
        message = self._format_singleton(result)
        self.log(f'Hit: {message}', sticky_header='Single channel assessment phase')

    def log_ratios(self, result: Result, confounding: tuple[Result, ...]) -> None:
        qualification = self._form_qualification(confounding)
        message = self._format_ratio(result)
        message = f'Hit: {message}   {qualification}'
        self.log(message, sticky_header='Channel ratios assessment phase')

    def log_proximity(self, result: Result, confounding: tuple[Result, ...]):
        qualification = self._form_qualification(confounding)
        message = self._format_proximity(result)
        message = f'Hit: {message}   {qualification}'
        self.log(message, sticky_header='Proximity assessment phase')

    def _form_qualification(self, confounding: tuple[Result, ...]) -> str:
        if len(confounding) > 0:
            strings = map(lambda r0: self._format_phenotype(r0.case.phenotype), confounding)
            reference = ', '.join(strings)
            qualification = f'(Probable confounding with {reference} results)'
        else:
            qualification = ''
        return qualification

    def _format_singleton(self, result: Result) -> str:
        s = result.significance
        w = self.name_width + 22
        p = self._format_phenotype((result.case.phenotype))
        pre = ('{:>' + str(w) + '}').format(f'{p} fractions in cohort {result.higher_cohort} (vs {result.lower_cohort()})')
        message = f'{pre} {self._format_effect(s.effect)}   {self._format_p(s.p)}  {self._format_quality(s.quality())}'
        return message

    def _format_effect(self, e: float) -> str:
        return '{:>12}'.format('%.4f' % e) + ' x'

    def _format_p(self, p: float) -> str:
        return '{:>12}'.format('p = ' + '%.5f' % p if p >= 0.0001 else '{:.2E}'.format(Decimal(p)))

    def _format_quality(self, q: float) -> str:
        return '{:>5}'.format('q = ' + '%.2f' % q)

    def _format_phenotype(self, p: PhenotypeCriteria) -> str:
        return ' '.join([x + '+' for x in p.positive_markers]) + ' '.join([x + '-' for x in p.negative_markers])

    def _format_ratio(self, result: Result) -> str:
        if result.case.other is None:
            raise ValueError('Only use this function for ratio features.')
        s = result.significance
        p1 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.phenotype))
        p2 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.other))
        pre = f'{p1} / {p2}   ratios in cohort {result.higher_cohort} (vs {result.lower_cohort()})'
        return f'{pre} {self._format_effect(s.effect)}   {self._format_p(s.p)}  {self._format_quality(s.quality())}'

    def _format_proximity(self, result: Result) -> str:
        if result.case.other is None:
            raise ValueError('Proximity requires two phenotypes.')
        s = result.significance
        p1 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.phenotype))
        p2 = ('{:>' + str(self.name_width + 1) + '}').format(self._format_phenotype(result.case.other))
        pre = f'{p1} have a number of nearby {p2}   cells in cohort {result.higher_cohort} (vs {result.lower_cohort()})'
        return f'{pre} {self._format_effect(s.effect)}   {self._format_p(s.p)}  {self._format_quality(s.quality())} '


