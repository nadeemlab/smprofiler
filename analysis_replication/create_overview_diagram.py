
import re
from collections import defaultdict
from collections import OrderedDict
from os.path import exists
from json import dumps as json_dumps
from json import loads as json_loads
from math import sqrt
from math import log10
from itertools import zip_longest
from xml.etree import ElementTree as ET
from urllib.parse import urlencode
from urllib.parse import quote_plus
from string import Template
from warnings import filterwarnings
from warnings import catch_warnings

from attrs import define

from pandas import merge
from pandas import read_csv
from pandas import read_sql
from pandas import concat
from pandas import DataFrame

from pystache import Renderer as PystacheRenderer
from pystache import parse as pystache_parse

from matplotlib import colormaps

from smprofiler.db.database_connection import DBConnection
from smprofiler.db.database_connection import DBCursor

from accessors import DataAccessor


class GatherSampleSummaryData:
    database_config_file: str

    def __init__(self, database_config_file = '.smprofiler_db.config'):
        self.database_config_file = database_config_file
        self.studies = self.get_studies()

    def get(self) -> tuple[DataFrame, dict]:
        filename = 'sources_and_strata.tsv'
        if not exists(filename):
            sources_and_strata, sample_names = self._gather_source_sites_and_strata()
            sources_and_strata.to_csv(filename, sep='\t', index=False)
            self._write_sample_names(sample_names)
        else:
            sources_and_strata = read_csv(filename, sep='\t', keep_default_na=False)
            sample_names = json_loads(open('sample_names.json', 'rt', encoding='utf-8').read())
        return sources_and_strata, sample_names

    def _gather_source_sites_and_strata(self) -> tuple[DataFrame, dict]:
        strata = self.get_sample_strata()
        source_sites = self.get_source_site_assignments()
        joined = strata.join(source_sites, on='sample')
        cell_counts = self.get_cell_counts()
        by_sample = merge(joined, cell_counts, on=['sample', 'study'], how='inner')
        by_sample['ones'] = int(1)
        columns = ['source_site', 'study', 'stratum_identifier', 'local_temporal_position_indicator', 'subject_diagnosed_condition', 'subject_diagnosed_result']
        sample_names = by_sample[['study', 'stratum_identifier', 'source_site', 'sample']]
        del by_sample['sample']
        aggregated = by_sample.groupby(columns).agg('sum')
        aggregated = aggregated.reset_index()
        aggregated = aggregated.rename(columns={'ones': 'sample_count'})
        return aggregated, self._form_nested_sample_names(sample_names)

    def _form_nested_sample_names(self, sample_names: DataFrame) -> dict:
        nested = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
        for study, group1 in sample_names.groupby('study'):
            for source_site, group2 in group1.groupby('source_site'):
                for stratum_identifier, group3 in group2.groupby('stratum_identifier'):
                    nested[study][source_site][stratum_identifier] = sorted(list(group3['sample']))
        return nested

    def _write_sample_names(self, sample_names: dict) -> None:
        sample_names_json = json_dumps(sample_names, indent=2)
        with open('sample_names.json', 'wt', encoding='utf-8') as file:
            file.write(sample_names_json)

    def get_sample_strata(self) -> DataFrame:
        query = '''
        SELECT sample, stratum_identifier, local_temporal_position_indicator, subject_diagnosed_condition, subject_diagnosed_result
        FROM sample_strata;
        '''
        return self.dataframe_combined_over_studies(query)

    def get_source_site_assignments(self) -> DataFrame:
        query = '''
        SELECT specimen, source_site
        FROM specimen_collection_process
        ORDER BY source_site, specimen;
        '''
        df = self.dataframe_combined_over_studies(query)
        df = df.rename(columns={'specimen': 'sample'})
        df = df.set_index('sample')
        del df['study']
        return df

    def dataframe_combined_over_studies(self, query: str) -> DataFrame:
        df = None
        for study in self.studies:
            with DBConnection(database_config_file=self.database_config_file, study=study) as connection:
                with catch_warnings():
                    filterwarnings('ignore', message='pandas only supports SQLAlchemy', category=UserWarning)
                    df_study = read_sql(query, connection)
            df_study['study'] = self.abbreviate_study_name(study)
            if df is None:
                df = df_study
            else:
                df = concat([df, df_study], axis=0)
        return df

    def get_cell_counts(self) -> DataFrame:
        counts = self.retrieve_cell_counts()
        counts = counts.rename(columns={'specimen': 'sample', 'count': 'cell_count'})
        counts = counts.set_index(['sample', 'study'])
        del counts['percentage']
        return counts

    def retrieve_cell_counts(self) -> DataFrame:
        query = 'phenotype-counts'
        access = DataAccessor(self.studies[0])
        df = None
        for study in self.studies:
            parameters = urlencode([('study', study), ('negative_marker', ''), ('positive_marker', '')])
            counts, _ = access._retrieve(query, parameters)
            _df = DataFrame(counts['counts'])
            _df['study'] = self.abbreviate_study_name(study)
            if df is None:
                df = _df
            else:
                df = concat([df, _df], axis=0)
        return df

    def get_studies(self) -> tuple[str, ...]:
        with DBCursor(database_config_file=self.database_config_file) as cursor:
            cursor.execute('SELECT study from study_lookup;')
            studies = tuple(map(lambda r: r[0], cursor.fetchall()))
        return studies

    @staticmethod
    def abbreviate_study_name(study: str) -> str:
        return study.split(' collection: ')[0]


ColorCodeLookup = dict[tuple[str, str], tuple[str, int]]

class ColorLookup:
    _lookup: ColorCodeLookup

    def __init__(self):
        df = read_csv('outcome_stratum_labels_annotations.tsv', sep='\t')
        lookup = {
            (row['study'], str(row['stratum_identifier'])): self._parse_matplotlib_color_spec(row['color'])
            for _, row in df.iterrows()
        }
        self._lookup = lookup

    def lookup(self, study: str, stratum_identifier: str, hex: bool=False) -> tuple[float, float, float, float]:
        color = self._get_mpl_color(*self._lookup[(study, stratum_identifier)])
        if hex:
            return self._to_hex(color)
        return color

    @staticmethod
    def _to_hex(color: tuple[float, float, float, float]) -> str:
        return '#%02x%02x%02x' % tuple(map(lambda v: min(255, int(v*256)), color[0:3]))

    @staticmethod
    def _parse_matplotlib_color_spec(c: str) -> tuple[str, int]:
        parts = c.split(';')
        return (parts[0], int(parts[1]))

    @staticmethod
    def _get_mpl_color(cmap_name: str, value: int):
        return colormaps[cmap_name](value)

    def get_ordinal(self, key: tuple[str, str]) -> int:
        keys = sorted(list(self._lookup.keys()))
        return keys.index(key)

    def get_keys(self) -> tuple[tuple[str, str], ...]:
        return sorted(list(self._lookup.keys()))


class SiteLabels:
    labels: dict[tuple[str, str], str]

    def __init__(self):
        self.labels = self._get_site_labels()

    def lookup(self, study: str, source_site: str) -> str:
        return self.labels[(study, source_site)]

    def _get_site_labels(self) -> dict[tuple[str, str], str]:
        df = read_csv('anatomical_labels_annotations.tsv', sep='\t', keep_default_na=False)
        lookup = {
            (row['study'], str(row['source_site'])): row['label']
            for _, row in df.iterrows()
        }
        return lookup


class OutcomeLabels:
    stratum_labels: dict[tuple[str, str], str]
    category_labels: dict[str, str]

    def __init__(self):
        df = read_csv('outcome_stratum_labels_annotations.tsv', sep='\t')
        df = df[~df['value label'].isna()]
        lookup = {
            row['study']: str(row['category label'])
            for _, row in df[['study', 'category label']].drop_duplicates().iterrows()
        }
        self.category_labels = lookup
        lookup = {
            (row['study'], str(row['stratum_identifier'])): str(row['value label'])
            for _, row in df.iterrows()
        }
        self.stratum_labels = lookup

    def get_category_label(self, study: str) -> str:
        return self.category_labels[study]

    def get_stratum_label(self, study: str, stratum_identifier: str) -> str:
        return self.stratum_labels[(study, stratum_identifier)]

    def get_studies(self) -> tuple[str, ...]:
        return tuple(self.category_labels.keys())

    def get_strata(self, study: str) -> tuple[tuple[str, str], ...]:
        return tuple(filter(lambda k: k[0] == study, self.stratum_labels.keys()))


@define
class LabelsColorsLookup:
    colors: ColorLookup
    site_labels: SiteLabels
    outcome_labels: OutcomeLabels


@define
class BoxDiagramSpecification:
    number_boxes_by_stratum: OrderedDict[str, int]
    width_count: int
    height_count: int
    aspect: float
    area_per_box: float
    total_cells: int
    study: str
    source_site: str


def _desired_area(cell_count: int) -> float:
    return pow(cell_count / pow(10, 5), 1/2)


def _specify_box_diagram(study: str, source_site: str, counts: DataFrame, all_counts: DataFrame) -> BoxDiagramSpecification:
    total_cells = float(counts['cell_count'].sum())
    target_area = _desired_area(total_cells)
    groupstrata = counts.copy().set_index('stratum_identifier')
    number_boxes_strata = groupstrata['sample_count']
    number_boxes_by_stratum = OrderedDict()
    for key, value in number_boxes_strata.items():
        number_boxes_by_stratum[key] = int(value)
    number_boxes = int(counts['sample_count'].sum())
    area_per_box = target_area / number_boxes

    total_cells_study = float(all_counts[all_counts['study'] == study]['cell_count'].sum())
    target_area_study = _desired_area(total_cells_study)
    desired_width_study = 8
    target_height_study = target_area_study / desired_width_study
    desired_average_width_portion = desired_width_study * pow(target_area / target_area_study, 4)
    desired_aspect = target_height_study / desired_average_width_portion

    aspect_attempted = desired_aspect
    width_count = max(1, round(sqrt(number_boxes / aspect_attempted)))
    remainder = number_boxes % width_count
    height_count = (number_boxes // width_count) + 1 if remainder > 0 else int(number_boxes / width_count)
    aspect = height_count / width_count
    return BoxDiagramSpecification(
        number_boxes_by_stratum,
        width_count,
        height_count,
        aspect,
        area_per_box,
        total_cells,
        study,
        source_site,
    )


class BoxDiagramBuilder:
    @classmethod
    def create_box_graphics_html(cls, spec: BoxDiagramSpecification, color_lookup: ColorLookup, sample_names: dict[str, list[str]]) -> str:
        """
        Creates a "box diagram" with color-coded boxes in a neat grid with desired
        size-related and aspect-related characteristics.
        In HTML format.
        """
        cls._check_counts(spec, sample_names)
        rows = cls._form_uniform_rows(spec, sample_names)
        df = DataFrame(rows)
        box_width = sqrt(spec.area_per_box)
        width = spec.width_count * box_width
        table_width = width * 100

        height = spec.height_count * box_width
        table_height = height * 100
        row_height = table_height / spec.height_count

        study_for_url = re.sub(' ', '-', spec.study.lower())

        e = ET.Element('table')
        e.set('class', 'box-diagram-graphics')
        e.set('width', f'{table_width}px')
        e1 = ET.SubElement(e, 'tbody')
        for _, row in df.iterrows():
            tr = ET.SubElement(e1, 'tr')
            tr.set('height', f'{row_height}px')
            for entry, sample_name in row:
                td = ET.SubElement(tr, 'td')
                if entry == 0:
                    o = 'blank'
                else:
                    o = color_lookup.get_ordinal((spec.study, str(entry)))
                    td.set('data-tooltip', sample_name)
                    td.set('class', f'sample-marker-clickable')
                    sample_name_for_url = quote_plus(sample_name)
                    td.set('onclick', f"window.location.href='https://smprofiler.io/study/{study_for_url}/slide-viewer/{sample_name_for_url}';")
                td.set('class', f'sample-group-color-{o} sample-marker')
        return ET.tostring(e, encoding='unicode')

    @classmethod
    def _form_uniform_rows(
        cls,
        spec: BoxDiagramSpecification,
        sample_names: dict[str, list[str]],
    ) -> list[tuple[tuple[int, str], ...]]:
        number_boxes_by_stratum = cls._apply_study_patches(spec.study, spec.number_boxes_by_stratum)
        cellvalues: list[tuple[int, str]] = []
        for key in number_boxes_by_stratum.keys():
            cellvalues.extend(list(map(lambda n: (key, n), sample_names[str(key)])))
        return list(zip_longest(*(iter(cellvalues),) * spec.width_count, fillvalue=(0, '')))  # type: ignore

    @classmethod
    def _check_counts(cls, spec: BoxDiagramSpecification, sample_names: dict[str, list[str]]) -> None:
        for stratum_identifier, count in spec.number_boxes_by_stratum.items():
            if count != len(sample_names[str(stratum_identifier)]):
                raise ValueError(f'Expected {sample_names[stratum_identifier]} = {len(sample_names[stratum_identifier])}')

    @classmethod
    def _apply_study_patches(cls, study: str, number_boxes_by_stratum: OrderedDict[str, int]) -> OrderedDict[str, int]:
        if study == 'Brain met IMC':
            def key(i):
                k = int(i)
                if k in [2, 3]:
                    return 2 + 3 - k
                return k
            keys = sorted(number_boxes_by_stratum, key=key)
            new = OrderedDict()
            for k in keys:
                new[k] = number_boxes_by_stratum[k]
            number_boxes_by_stratum = new
        return number_boxes_by_stratum


class FigureTemplateValuesBuilder:
    template_values: dict
    lookup: LabelsColorsLookup
    sample_names: dict

    def __init__(self, sources_and_strata: DataFrame, lookup: LabelsColorsLookup, sample_names: dict):
        self.lookup = lookup
        self.sample_names = sample_names
        self.template_values = self._form_template_values(sources_and_strata)

    def get_template_values(self) -> dict:
        return self.template_values

    def _form_template_values(self, sources_and_strata: DataFrame) -> dict:
        studies = [
            self._form_values_one_study(study, group)
            for study, group in sources_and_strata.groupby('study')
        ]
        studies = sorted(studies, key=lambda s: len(s['study']['sample_groups']))
        return {
            'colormap_items': self._form_values_colormap(),
            'studies': studies
        }

    def _form_values_one_study(self, study: str, df: DataFrame) -> dict:
        return {
            'study': {
                'name': study,
                'sample_groups': [
                    self._form_values_one_box_diagram(_specify_box_diagram(study, source_site, group, df))
                    for source_site, group in df.groupby('source_site')
                ],
                'legend': self._form_values_legend(study),
            }
        }

    def _form_values_one_box_diagram(self, spec: BoxDiagramSpecification) -> dict:
        return {
            'sample_group': {
                'site_name': self.lookup.site_labels.lookup(spec.study, spec.source_site),
                'total_cells_short': self._abbreviate_int(spec.total_cells),
                'payload': BoxDiagramBuilder.create_box_graphics_html(
                    spec,
                    self.lookup.colors,
                    self.sample_names[spec.study][spec.source_site],
                ),
            }
        }

    def _form_values_legend(self, study: str) -> dict:
        return {
            'title': self.lookup.outcome_labels.get_category_label(study),
            'items': [
                {
                    'item': {
                        'text': self.lookup.outcome_labels.get_stratum_label(study, stratum_identifier),
                        'color_id': self.lookup.colors.get_ordinal((study, stratum_identifier)),
                    }
                }
                for _, stratum_identifier in self.lookup.outcome_labels.get_strata(study)
            ],
        }

    def _form_values_colormap(self) -> list:
        return [
            {
                'item': {
                    'color_id': self.lookup.colors.get_ordinal(key),
                    'hex_color': self.lookup.colors.lookup(*key, hex=True),
                }
            }
            for key in self.lookup.colors.get_keys()
        ]

    @staticmethod
    def _abbreviate_int(i: int | float) -> str:
        i = int(i)
        scale = log10(i)
        if scale >= 6:
            return str(round((i / pow(10, 6)))) + 'm'
        if scale >= 3:
            return str(round((i / pow(10, 3)))) + 'k'
        return str(i)


@define
class SampleBoxesOverviewFigure:
    css: str
    table_html: str
    template_values: dict


class SampleBoxesOverview:
    file_basename: str
    sources_and_strata: DataFrame | None
    sample_names: dict
    lookup: LabelsColorsLookup
    figure: SampleBoxesOverviewFigure | None

    def __init__(self, file_basename: str='overview_diagram'):
        """
        `file_basename` is the base for the HTML and CSS files that are supposed
        to be the template source files.
        """
        self.file_basename = file_basename
        self.sources_and_strata = None
        self.figure = None

    def get_figure(self) -> SampleBoxesOverviewFigure:
        """
        Generates an overview figure representing each sample in the database as
        a color-coded box in a box diagrams. Boxes are arranged in groups by study/
        dataset and anatomical source site, and color-coded by outcome assignments.
        
        Returns the figure in the format of HTML, CSS, and nested template values
        used to create them.
        """
        self._create()
        return self.figure

    def create_and_write_to_file(self, file_basename: str='overview_diagram') -> None:
        """
        Convenience function to create the figure, then write to HTML (the figure)
        and JSON file (the template values).
        """
        self._create()
        self._write_html_figure(file_basename)
        self._stash_template_values(file_basename)

    def _create(self) -> None:
        if self.sources_and_strata is None:
            self._retrieve_input_data()
        if self.figure is None:
            self._generate_html_diagram()

    def _retrieve_input_data(self) -> None:
        self.sources_and_strata, self.sample_names = GatherSampleSummaryData().get()
        self.lookup = LabelsColorsLookup(ColorLookup(), SiteLabels(), OutcomeLabels())

    def _generate_html_diagram(self) -> None:
        css, table, template_values = self._get_html_diagram_parts()
        self.figure = SampleBoxesOverviewFigure(css, table, template_values)

    def _get_html_diagram_parts(self) -> tuple[str, str, dict]:
        template_values = FigureTemplateValuesBuilder(self.sources_and_strata, self.lookup, self.sample_names).get_template_values()
        table = self._get_figure_table(template_values)
        css = self._get_figure_css(template_values)
        return css, table, template_values

    def _get_figure_css(self, template_values: dict) -> str:
        css_template = pystache_parse(open(f'{self.file_basename}.template.css', 'rt', encoding='utf-8').read())
        return PystacheRenderer().render(css_template, template_values)

    def _get_figure_table(self, template_values: dict) -> str:
        table_template = pystache_parse(open(f'{self.file_basename}.template.html', 'rt', encoding='utf-8').read())
        return PystacheRenderer().render(table_template, template_values)

    def _write_html_figure(self, file_basename: str) -> None:
        html_template = '''
        <html>
          <head>
            <style>
              $css
            </style>
          </head>
          <body>
            $body
          </body>
        </html>
        '''
        html = Template(html_template).substitute(css=self.figure.css, body=self.figure.table_html)
        with open(f'{file_basename}.html', 'wt', encoding='utf-8') as file:
            file.write(html)

    def _stash_template_values(self, file_basename: str) -> None:
        values_json = json_dumps(self.figure.template_values, indent=2)
        with open(f'{file_basename}.json', 'wt', encoding='utf-8') as file:
            file.write(values_json)


if __name__=='__main__':
    figure = SampleBoxesOverview()
    figure.create_and_write_to_file()
