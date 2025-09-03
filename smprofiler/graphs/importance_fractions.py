"""GNN importance fractions figure generation."""

from os.path import exists
from pickle import load as pickle_load
from pickle import dump as pickle_dump
from typing import Literal
from typing import Iterable
from typing import cast
from typing import Any
from typing import Callable
from typing import TYPE_CHECKING
import re
from itertools import chain
from urllib.parse import urlencode
from enum import Enum

import numpy as np
from numpy.typing import NDArray
from pandas import DataFrame
from pandas import MultiIndex
from pandas import concat
from pandas import Series
import matplotlib.pyplot as plt  # type: ignore
from matplotlib.pyplot import Axes
import matplotlib.colors as mcolors  # type: ignore
from matplotlib.colors import Normalize
from scipy.stats import fisher_exact  # type: ignore
from attr import define
from pydantic import BaseModel

from smprofiler.standalone_utilities.log_formats import colorized_logger
logger = colorized_logger(__name__)

if TYPE_CHECKING:
    from matplotlib.figure import Figure  # type: ignore

GNNModel = Literal['cg-gnn', 'graph-transformer']


@define
class Cohort:
    index_int: int
    label: str


class Orientation(Enum):
    HORIZONTAL = 'horizontal'
    VERTICAL = 'vertical'


@define
class PlotSpecification:
    study: str
    phenotypes: tuple[str, ...]
    cohorts: tuple[Cohort, ...]
    plugins: tuple[GNNModel, ...]
    figure_size: tuple[float, float]
    orientation: Orientation


def sanitized_study(study: str) -> str:
    return re.sub(' ', '_', study).lower()


PhenotypeDataFrames = tuple[tuple[str, DataFrame], ...]

APIServerCallables = tuple[
    Callable[[list[str], list[str], str], BaseModel],
    Callable[[str], BaseModel],
    Callable[[str, str], BaseModel],
    Callable[[
        str,
        list[str],
        list[str],
        str,
        dict[str, Any],
    ], BaseModel],
]


class Colors:
    bold_magenta = '\u001b[35;1m'
    reset = '\u001b[0m'


class ImportanceCountsAccessor:
    """Convenience caller of HTTP methods for access of phenotype counts and importance scores."""

    def __init__(
        self,
        study: str,
        what_to_query: str | APIServerCallables,
    ) -> None:
        self.use_http = False
        self.host: str | None = None
        self.query_anonymous_phenotype_counts_fast: Callable[[
            list[str], list[str], str], Any] | None = None
        self.query_study_summary: Callable[[str], Any] | None = None
        self.query_phenotype_criteria: Callable[[str, str], Any] | None = None
        self.query_importance_composition: Callable[[
            str,
            list[str],
            list[str],
            str,
            dict[str, Any],
        ], Any] | None = None
        if isinstance(what_to_query, str):
            if re.search('^http://', what_to_query):
                self.use_http = True
                what_to_query = re.sub(r'^http://', '', what_to_query)
            self.host = what_to_query
        else:
            (
                self.query_anonymous_phenotype_counts_fast,
                self.query_study_summary,
                self.query_phenotype_criteria,
                self.query_importance_composition,
            ) = what_to_query
        self.study = study
        print('\n' + Colors.bold_magenta + study + Colors.reset + '\n')
        self.cohorts = self._retrieve_cohorts()
        self.all_cells = self._retrieve_all_cells_counts()

    def counts(self, phenotype_names: str | list[str]) -> DataFrame:
        if isinstance(phenotype_names, str):
            phenotype_names = [phenotype_names]
        conjunction_criteria = self._conjunction_phenotype_criteria(phenotype_names)
        all_name = self.name_for_all_phenotypes(phenotype_names)
        conjunction_counts_series = self._get_counts_series(conjunction_criteria, all_name)
        individual_counts_series = [
            self._get_counts_series(self._phenotype_criteria(name), self._name_phenotype(name))
            for name in phenotype_names
        ]
        df = concat(
            [self.cohorts, self.all_cells, conjunction_counts_series, *individual_counts_series],
            axis=1,
        )
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df

    def name_for_all_phenotypes(self, phenotype_names: list[str]) -> str:
        return ' and '.join([self._name_phenotype(p) for p in phenotype_names])

    def counts_by_signature(self, positives: list[str], negatives: list[str]) -> dict[str, Any]:
        if (not positives) and (not negatives):
            raise ValueError('At least one positive or negative marker is required.')
        if not positives:
            positives = ['']
        elif not negatives:
            negatives = ['']
        if self.host is not None:
            parts = list(chain(*[
                [(f'{keyword}_marker', channel) for channel in argument]
                for keyword, argument in zip(['positive', 'negative'], [positives, negatives])
            ]))
            parts = sorted(list(set(parts)))
            parts.append(('study', self.study))
            query = urlencode(parts)
            endpoint = 'anonymous-phenotype-counts-fast'
            return self._retrieve(endpoint, query)[0]
        else:
            assert self.query_anonymous_phenotype_counts_fast is not None
            return self.query_anonymous_phenotype_counts_fast(positives, negatives, self.study).dict()

    def _get_counts_series(self, criteria: dict[str, list[str]], column_name: str) -> Series:
        criteria_tuple = (
            criteria['positive_markers'],
            criteria['negative_markers'],
        )
        counts = self.counts_by_signature(*criteria_tuple)
        df = DataFrame(counts['counts'])
        mapper = {'specimen': 'sample', 'count': column_name}
        return df.rename(columns=mapper).set_index('sample')[column_name]

    def _retrieve_cohorts(self) -> DataFrame:
        if self.host is not None:
            summary, _ = self._retrieve('study-summary', urlencode([('study', self.study)]))
        else:
            assert self.query_study_summary is not None
            summary = self.query_study_summary(self.study).dict()
        return DataFrame(summary['cohorts']['assignments']).set_index('sample')

    def _retrieve_all_cells_counts(self) -> Series:
        counts = self.counts_by_signature([''], [''])
        df = DataFrame(counts['counts'])
        all_name = 'all cells'
        mapper = {'specimen': 'sample', 'count': all_name}
        counts_series = df.rename(columns=mapper).set_index('sample')[all_name]
        return counts_series

    def _get_base(self) -> str:
        protocol = 'https'
        if self.host is not None and (self.host == 'localhost' or re.search('127.0.0.1', self.host) or self.use_http):
            protocol = 'http'
        return '://'.join((protocol, cast(str, self.host)))

    def _retrieve(self, endpoint: str, query: str) -> tuple[dict[str, Any], str]:
        from requests import get as get_request  # type: ignore
        base = f'{self._get_base()}'
        url = '/'.join([base, endpoint, '?' + query])
        try:
            content = get_request(url, timeout=200)
        except Exception as exception:
            print(url)
            raise exception
        return content.json(), url

    def _phenotype_criteria(self, name: str | dict[str, list[str]]) -> dict[str, list[str]]:
        if isinstance(name, dict):
            criteria = name
            keys = ['positive_markers', 'negative_markers']
            for key in keys:
                if criteria[key] == []:
                    criteria[key] = ['']
            return criteria
        if self.host is not None:
            query = urlencode([('study', self.study), ('phenotype_symbol', name)])
            criteria, _ = self._retrieve('phenotype-criteria', query)
        else:
            assert self.query_phenotype_criteria is not None
            criteria = self.query_phenotype_criteria(self.study, name).dict()
        return criteria

    def _conjunction_phenotype_criteria(self, names: list[str]) -> dict[str, list[str]]:
        criteria_list: list[dict[str, list[str]]] = []
        for name in names:
            criteria = self._phenotype_criteria(name)
            criteria_list.append(criteria)
        return self._merge_criteria(criteria_list)

    def _merge_criteria(self, criteria_list: list[dict[str, list[str]]]) -> dict[str, list[str]]:
        keys = ['positive_markers', 'negative_markers']
        merged = {
            key: sorted(list(set(list(chain(*[criteria[key] for criteria in criteria_list])))))
            for key in keys
        }
        for key in keys:
            if merged[key] == []:
                merged[key] = ['']
        return merged

    def _name_phenotype(self, phenotype: str) -> str:
        if isinstance(phenotype, dict):
            return ' '.join([
                ' '.join([f'{p}{sign}' for p in phenotype[f'{keyword}_markers'] if p != ''])
                for keyword, sign in zip(['positive', 'negative'], ['+', '-'])
            ]).rstrip()
        return str(phenotype)

    def important(
        self,
        phenotype_names: str | list[str],
        plugin: str = 'cg-gnn',
        datetime_of_run: str | None = None,
        plugin_version: str | None = None,
        cohort_stratifier: str | None = None,
    ) -> dict[str, float]:
        if isinstance(phenotype_names, str):
            phenotype_names = [phenotype_names]
        conjunction_criteria = self._conjunction_phenotype_criteria(phenotype_names)
        if self.host is not None:
            parts = list(chain(*[
                [(f'{keyword}_marker', channel) for channel in argument]
                for keyword, argument in zip(
                    ['positive', 'negative'], [
                        conjunction_criteria['positive_markers'],
                        conjunction_criteria['negative_markers'],
                    ])
            ]))
            parts = sorted(list(set(parts)))
            parts.append(('study', self.study))
            if plugin in {'cg-gnn', 'graph-transformer'}:
                parts.append(('plugin', plugin))
            else:
                raise ValueError(f'Unrecognized plugin name: {plugin}')
            if datetime_of_run is not None:
                parts.append(('datetime_of_run', datetime_of_run))
            if plugin_version is not None:
                parts.append(('plugin_version', plugin_version))
            if cohort_stratifier is not None:
                parts.append(('cohort_stratifier', cohort_stratifier))
            query = urlencode(parts)
            phenotype_counts, _ = self._retrieve('importance-composition', query)
        else:
            assert self.query_importance_composition is not None
            optional_args = {
                'datetime_of_run': datetime_of_run,
                'plugin_version': plugin_version,
                'cohort_stratifier': cohort_stratifier,
            }
            optional_args = {k: v for k, v in optional_args.items() if v is not None}

            phenotype_counts = (self.query_importance_composition(
                self.study,
                conjunction_criteria['positive_markers'],
                conjunction_criteria['negative_markers'],
                plugin,
                **optional_args,
            )).dict()  # type: ignore
        return {c['specimen']: c['percentage'] for c in phenotype_counts['counts']}


class ImportanceFractionAndTestRetriever:
    df_phenotypes: PhenotypeDataFrames | None
    df_phenotypes_original: PhenotypeDataFrames | None

    def __init__(
        self,
        host: str | APIServerCallables,
        study: str,
        count_important: int = 100,
        use_tqdm: bool = False,
    ) -> None:
        self.host = host
        self.study = study
        self.count_important = count_important
        self.use_tqdm = use_tqdm

        self.df_phenotypes = None
        self.df_phenotypes_original = None
        self.access = ImportanceCountsAccessor(self.study, self.host)

    def get_access(self) -> ImportanceCountsAccessor:
        return self.access

    def get_df_phenotypes(self) -> PhenotypeDataFrames:
        if self.df_phenotypes is None:
            raise RuntimeError('Phenotype dataframes have not been initialized.')
        return cast(PhenotypeDataFrames, self.df_phenotypes)

    def get_sanitized_study(self) -> str:
        return sanitized_study(self.study)

    def get_pickle_file(self, data: Literal['counts', 'importance'], plugin: GNNModel | None = None) -> str:
        if data == 'counts':
            return f'{self.get_sanitized_study()}.df_phenotypes.pickle'
        if data == 'importance':
            return f'{self.get_sanitized_study()}.{plugin}.pickle'

    @staticmethod
    def get_progress_bar_format() -> str:
        return '{l_bar}{bar:30}{r_bar}{bar:-30b}'

    def reset_phenotype_counts(self, df: DataFrame) -> None:
        if self.df_phenotypes_original is None:
            self._retrieve_phenotype_counts(df)
        self.df_phenotypes = tuple(
            (phenotype, _df.copy())
            for phenotype, _df in cast(PhenotypeDataFrames, self.df_phenotypes_original)
        )

    def _retrieve_phenotype_counts(self, df: DataFrame) -> None:
        pickle_file = self.get_pickle_file('counts')
        if exists(pickle_file):
            with open(pickle_file, 'rb') as file:
                self.df_phenotypes_original = pickle_load(file)
                print(f'Loaded from cache: {pickle_file}')
        else:
            levels = df.columns.get_level_values(0).unique()
            N = len(levels)
            print('Retrieving count data to support plot.')
            f = self.get_progress_bar_format()

            iterable: Iterable
            if self.use_tqdm:
                from tqdm import tqdm  # type: ignore
                iterable = tqdm(levels, total=N, bar_format=f)
            else:
                iterable = levels
            df_phenotypes_original = []
            for phenotype in iterable:
                df_phenotypes_original.append((str(phenotype), self.get_access().counts(phenotype).astype(int)))
            self.df_phenotypes_original = tuple(df_phenotypes_original)
            with open(pickle_file, 'wb') as file:
                pickle_dump(self.df_phenotypes_original, file)

    def retrieve(self, cohorts: set[int], phenotypes: list[str], plugin: GNNModel) -> DataFrame:
        multiindex = MultiIndex.from_product([phenotypes, ['p_value', 'important_fraction']])
        df = DataFrame(columns=multiindex)
        self.reset_phenotype_counts(df)
        print(f'Retrieving important cell fractions ({plugin}).')
        N = len(self.get_df_phenotypes())
        pickle_file = self.get_pickle_file('importance', plugin=plugin)
        f = self.get_progress_bar_format()
        if exists(pickle_file):
            with open(pickle_file, 'rb') as file:
                important_proportions = pickle_load(file)
                print(f'Loaded from cache: {pickle_file}')
        else:
            iterable: PhenotypeDataFrames
            if self.use_tqdm:
                from tqdm import tqdm
                iterable = tqdm(self.get_df_phenotypes(), total=N, bar_format=f)  # type: ignore
            else:
                iterable = self.get_df_phenotypes()
            important_proportions = {
                phenotype: self.get_access().important(phenotype, plugin=plugin)
                for phenotype, _ in iterable
            }
            with open(pickle_file, 'wb') as file:
                pickle_dump(important_proportions, file)
        omittable = self._get_omittable_samples(important_proportions)
        self._restrict_rows(cohorts, omittable)
        cohort_column = self._get_cohort_column().astype(int)
        self._restrict_columns()
        for phenotype, df_phenotype in self.get_df_phenotypes():
            important_proportion = important_proportions[phenotype]
            for _sample, row in df_phenotype.iterrows():
                sample = str(_sample)
                count_both = important_proportion[sample] * self.count_important / 100
                test = self._test_one_case
                test(phenotype, sample, row[phenotype], count_both, row['all cells'], df)
        self._get_cell_count()
        df['cohort'] = cohort_column
        return df

    def _test_one_case(
        self,
        phenotype: str,
        _sample: str,
        count_phenotype: int,
        count_both,
        total: int,
        df: DataFrame,
    ) -> None:
        if count_both > count_phenotype:
            message = f'Count {count_both} for both phenotype and selected exceeds count {count_phenotype} for phenotype alone.'
            logger.error(message)
        sample = str(_sample)
        a = count_both
        b = self.count_important - count_both
        c = count_phenotype - count_both
        d = total - a - b - c
        _, p_value = fisher_exact([[a, b], [c, d]])
        df.loc[sample, (phenotype, 'important_fraction')] = count_both / self.count_important
        df.loc[sample, (phenotype, 'p_value')] = p_value

    def _restrict_rows(self, cohorts: set[int], omittable: set[str]) -> None:
        self.df_phenotypes = tuple(
            (
                phenotype,
                df[df['cohort'].isin(cohorts) & ~df.index.isin(omittable)]
                .reset_index()
                .sort_values(['cohort', 'sample'])
                .set_index('sample'),
            )
            for phenotype, df in self.get_df_phenotypes()
        )

    def _restrict_columns(self) -> None:
        self.df_phenotypes = tuple(
            (
                phenotype,
                df.iloc[:, [
                    df.columns.get_loc('all cells'),
                    df.columns.get_indexer_for([phenotype])[0],
                ]],
            )
            for phenotype, df in self.get_df_phenotypes()
        )

    def _get_cohort_column(self) -> Series:
        cohort_column: Series | None = None
        for _, df_phenotype in self.get_df_phenotypes():
            if cohort_column is None:
                cohort_column = df_phenotype['cohort']
            else:
                assert (cohort_column == df_phenotype['cohort']).all()
        assert not cohort_column is None
        return cohort_column

    def _get_omittable_samples(
        self,
        important_proportions: dict[str, dict[str, float]],
    ) -> set[str]:
        occurring = set(
            str(sample)
            for _, df in self.get_df_phenotypes()
            for _, sample in Series(df.index).items()
        )
        with_none = set(
            str(sample)
            for _, important_proportion in important_proportions.items()
            for sample, value in important_proportion.items()
            if value is None
        )
        return occurring.intersection(with_none)

    def _get_cell_count(self) -> Series:
        cell_count = None
        for _, df in self.get_df_phenotypes():
            if cell_count is None:
                cell_count = df['all cells']
            else:
                assert (cell_count == df['all cells']).all()
        assert not cell_count is None
        return cell_count


@define
class PlotDataRetriever:
    host: str | APIServerCallables
    use_tqdm: bool

    def retrieve_data(self, specification: PlotSpecification) -> tuple[DataFrame, ...]:
        cohorts = set(c.index_int for c in specification.cohorts)
        plugins = cast(tuple[GNNModel, GNNModel], specification.plugins)
        phenotypes = list(specification.phenotypes)
        attribute_order = phenotypes + ['cohort']
        retriever = ImportanceFractionAndTestRetriever(
            self.host,
            specification.study,
            use_tqdm=self.use_tqdm,
        )
        retrieved = []
        for plugin in plugins:
            item = retriever.retrieve(cohorts, phenotypes, plugin)[attribute_order]
            retrieved.append(item)
        return tuple(retrieved)


@define
class SubplotGenerator:
    title_location: str
    norm: Normalize
    disc_scale_factor: float = 200

    def plot(
        self,
        df: DataFrame,
        ax: Axes,
        title: str,
        label_vertically: bool,
        label_horizontally: bool,
    ) -> None:
        """Plot the important fractions and p-values for the given dataframe."""
        s_cohort = df['cohort']
        cohorts = s_cohort.unique()

        df = self._prepare_dataframe(df, cohorts)
        df_p_value_normalized, df_p_important = self._get_p_values(df)
        X, Y = self._create_meshgrid(df_p_important)

        c, s = self._flatten_data(df_p_important, df_p_value_normalized)

        self._plot_scatter(ax, X, Y, c, s)
        self._set_axes(ax, df_p_important)
        self._add_labels(ax,
                         s_cohort,
                         cohorts,
                         df_p_important,
                         label_vertically,
                         label_horizontally,
                         )
        self._set_title(ax, title)

    def _prepare_dataframe(self, df: DataFrame, cohorts: NDArray[Any]) -> DataFrame:
        """Prepare the dataframe for plotting by adding NaN rows between cohorts."""
        dfs = []
        for i, cohort in enumerate(cohorts):
            df_cohort = df[df['cohort'] == cohort]
            if i != 0:
                df_cohort = concat([DataFrame([np.repeat(np.nan, df_cohort.shape[1])],
                                              columns=df_cohort.columns,
                                              index=[''],
                                              ), df_cohort])
            dfs.append(df_cohort)
        df = concat(dfs)
        df.index.name = 'Specimen by cohort'
        df.drop('cohort', axis=1, level=0, inplace=True)

        return df.transpose().astype(float)

    def _get_p_values(self, df: DataFrame) -> tuple[DataFrame, DataFrame]:
        """Get, clip, and normalize the p-values and important fractions from the dataframe."""
        df_p_value = df.xs('p_value', axis=0, level=1)
        df_p_important = df.xs('important_fraction', axis=0, level=1)

        df_p_value_clipped = df_p_value.clip(upper=0.05)
        df_p_value_normalized = 1 - df_p_value_clipped / 0.05

        return cast(DataFrame, df_p_value_normalized), cast(DataFrame, df_p_important)

    def _create_meshgrid(self, df_p_important: DataFrame) -> tuple[NDArray[Any], NDArray[Any]]:
        """Create a meshgrid for the cell centers."""
        x = np.arange(df_p_important.shape[1]) + 0.5
        y = np.arange(df_p_important.shape[0]) + 0.5
        X, Y = np.meshgrid(x, y)
        return X, Y

    def _flatten_data(self,
                      df_p_important: DataFrame,
                      df_p_value_normalized: DataFrame,
                      ) -> tuple[NDArray[Any], NDArray[Any]]:
        """Flatten the data and the sizes and scale up the latter for visibility."""
        c = df_p_important.values.flatten()
        s = df_p_value_normalized.values.flatten() * self.disc_scale_factor
        return c, s

    def _plot_scatter(self,
                      ax: Axes,
                      X: NDArray[Any],
                      Y: NDArray[Any],
                      c: NDArray[Any],
                      s: NDArray[Any],
                      ) -> None:
        ax.scatter(X.flatten(),
                   Y.flatten(),
                   c=c,
                   s=s,
                   cmap=self._get_main_heatmap_colormap(),
                   norm=self.norm,
                   edgecolor='black',
                   )
        ax.set_aspect('equal')
        # ax.set_aspect((df_p_important.shape[0] + len(cohorts) - 1) / df_p_important.shape[1]*1.5)

    def _set_axes(self, ax: Axes, df_p_important: DataFrame) -> None:
        """Invert the y-axis and turn off x-tick labels."""
        ax.set_xlim(0, df_p_important.shape[1])
        ax.set_ylim(0, df_p_important.shape[0])
        ax.invert_yaxis()

        ax.tick_params(axis='x', length=0)

    def _add_labels(self,
                    ax: Axes,
                    s_cohort: Series,
                    cohorts: NDArray[Any],
                    df_p_important: DataFrame,
                    label_vertically: bool,
                    label_horizontally: bool,
                    ) -> None:
        """Add text annotations to the plot to label the cohort and phenotype."""
        if label_horizontally:
            start = 0
            for cohort in cohorts:
                ax.text(start, -0.25, cohort if isinstance(cohort, str) else f'Cohort {cohort}',
                        ha='left', va='center')
                start += s_cohort[s_cohort == cohort].shape[0] + 1  # plus the NaN row
        ax.set_xticks([])

        if label_vertically:
            ax.set_yticks(np.arange(df_p_important.shape[0]) + 0.5)
            ax.set_yticklabels(df_p_important.index, rotation=0)
        else:
            ax.set_yticks([])
        ax.yaxis.set_ticks_position('none')

    def _set_title(self, ax: Axes, title: str) -> None:
        if self.title_location == 'bottom':
            ax.set_xlabel(title)
        else:
            ax.text(1.021, .5, title, rotation=-90, ha='right', va='center', transform=ax.transAxes)

    @staticmethod
    def _get_main_heatmap_colormap():
        colors = ['white', 'red']
        cmap = mcolors.LinearSegmentedColormap.from_list('', colors)
        cmap.set_under(color='white')
        return cmap


@define
class SubplotSpecification:
    grid_dimensions: tuple[int, int]
    title_location: Literal['bottom', 'side']


def derive_subplot_specification(specification: PlotSpecification) -> SubplotSpecification:
    size = len(specification.plugins)
    specs = {
        Orientation.HORIZONTAL: SubplotSpecification((1, size), 'bottom'),
        Orientation.VERTICAL: SubplotSpecification((size, 1), 'side'),
    }
    return specs[specification.orientation]


Indicator = tuple[bool, ...]
Indicators = tuple[Indicator, Indicator]


@define
class LabelIndicators:
    size: int
    baseline_orientation: Orientation

    def label_indicator_first(self) -> Indicator:
        return tuple([True] + list(map(lambda _: False, range(1, self.size))))

    def label_indicator_all(self) -> Indicator:
        return tuple(map(lambda _: True, range(self.size)))

    def get_label_subplot_indicators(self) -> Indicators:
        indicators = (
            self.label_indicator_first(),
            self.label_indicator_all(),
        )
        if self.baseline_orientation == Orientation.HORIZONTAL:
            return indicators
        if self.baseline_orientation == Orientation.VERTICAL:
            return cast(Indicators, tuple(reversed(indicators)))


def label_indicators(spec: PlotSpecification) -> LabelIndicators:
    return LabelIndicators(len(spec.plugins), spec.orientation)


class PlotGenerator:
    """Generate a importance fractions plot."""

    def __init__(
        self,
        what_to_query: str | APIServerCallables,
        study_name: str,
        phenotypes: list[str],
        cohorts_raw: list[tuple[int, str]],
        plugins: list[str],
        figure_size: tuple[int, int],
        orientation: str | None,
        use_tqdm: bool = False,
    ) -> None:
        """Instantiate the importance fractions plot generator."""
        self.host = what_to_query
        cohorts: list[Cohort] = []
        for cohort in cohorts_raw:
            cohorts.append(Cohort(*cohort))
        for model in plugins:
            if model != 'cg-gnn' and model != 'graph-transformer':
                raise ValueError(f'Unrecognized plugin name: {model}')
        self.specification = PlotSpecification(
            study_name,
            tuple(phenotypes),
            tuple(cohorts),
            cast(tuple[GNNModel], tuple(plugins)),
            figure_size,
            Orientation.HORIZONTAL if (orientation is None) else Orientation[orientation.upper()],
        )
        self.use_tqdm = use_tqdm

    def generate_plot(self) -> 'Figure':
        self._check_viability()
        dfs = self._retrieve_data()
        self._gather_subplot_cases(dfs)
        return self._generate_subplots(dfs)

    def _check_viability(self) -> None:
        if len(self.specification.plugins) != 2:
            raise ValueError('Currently plot generation requires 2 plugins worth of run data.')

    def _retrieve_data(self) -> tuple[DataFrame, ...]:
        dfs = PlotDataRetriever(self.host, self.use_tqdm).retrieve_data(self.specification)
        dfs = self._transfer_cohort_labels(dfs, self.specification)
        return dfs

    def _transfer_cohort_labels(
        self,
        dfs: tuple[DataFrame, ...],
        specification: PlotSpecification,
    ) -> tuple[DataFrame, ...]:
        if specification.cohorts is not None:
            cohort_map = {c.index_int: c.label for c in specification.cohorts}
            dfs = tuple(df.copy() for df in dfs)
            for _, df in enumerate(dfs):
                df['cohort'] = df['cohort'].map(cohort_map)
        dfs = tuple(df.sort_values('cohort').sort_index() for df in dfs)
        return dfs

    def _gather_subplot_cases(
        self,
        dfs: tuple[DataFrame, ...],
    ) -> tuple[SubplotSpecification, Indicators, Iterable[tuple[DataFrame, GNNModel]]]:
        subplot_specification = derive_subplot_specification(self.specification)
        indicators = label_indicators(self.specification).get_label_subplot_indicators()
        return subplot_specification, indicators, zip(dfs, self.specification.plugins)

    def _generate_subplots(self, dfs: tuple[DataFrame, ...]) -> 'Figure':
        plt.rcParams['font.size'] = 14
        norm = self._generate_normalization(dfs)
        subplot_specification, indicators, cases = self._gather_subplot_cases(dfs)
        fig, axs = plt.subplots(
            *subplot_specification.grid_dimensions,
            figsize=self.specification.figure_size,
        )
        title_location = subplot_specification.title_location
        subplot_generator = SubplotGenerator(title_location, norm)
        for i, ((df, plugin), ax) in enumerate(zip(cases, axs)):
            subplot_generator.plot(df, ax, plugin, indicators[0][i], indicators[1][i])
        fig.suptitle(self.specification.study)
        plt.tight_layout()
        return fig

    @staticmethod
    def _generate_normalization(dfs: tuple[DataFrame, ...]) -> Normalize:
        dfs_values_only = tuple(df.drop('cohort', axis=1, level=0) for df in dfs)
        vmin = min(df.min().min() for df in dfs_values_only)
        vmax = max(df.max().max() for df in dfs_values_only)
        return Normalize(vmin=vmin, vmax=vmax)
