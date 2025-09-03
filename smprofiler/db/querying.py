"""Some basic accessors that retrieve from the database."""

import re

from pandas import read_sql  # type: ignore

from smprofiler.db.database_connection import QueryCursor
from smprofiler.db.exchange_data_formats.study import (
    StudyComponents,
    StudyHandle,
    StudySummary,
    ChannelAnnotations,
    ChannelGroupAnnotation,
    ChannelAliases,
)
from smprofiler.db.exchange_data_formats.metrics import (
    PhenotypeSymbol,
    Channel,
    PhenotypeCriteria,
    AvailableGNN,
)
from smprofiler.db.exchange_data_formats.cells import CellsData
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.accessors.graphs import GraphsAccess
from smprofiler.db.accessors.phenotypes import PhenotypesAccess
from smprofiler.db.accessors.study import StudyAccess
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.standalone_utilities import sort


class QueryHandler:
    """Handle simple queries to the database."""
    @classmethod
    def get_study_components(cls, cursor, study: str) -> StudyComponents:
        return StudyAccess(cursor).get_study_components(study)

    @classmethod
    def retrieve_study_specifiers(cls, cursor) -> tuple[str, ...]:
        return sort(StudyAccess(cursor).get_study_specifiers())

    @classmethod
    def retrieve_study_handle(cls, cursor, study: str) -> StudyHandle:
        return StudyAccess(cursor).get_study_handle(study)

    @classmethod
    def get_study_summary(cls, cursor, study: str) -> StudySummary:
        return StudyAccess(cursor).get_study_summary(study)

    @classmethod
    def is_public_collection(cls, cursor, collection: str) -> bool:
        whitelist = StudyAccess(cursor).get_collection_whitelist()
        return collection in whitelist

    @classmethod
    def get_available_gnn(cls, cursor, study: str) -> AvailableGNN:
        return StudyAccess(cursor).get_available_gnn(study)

    @classmethod
    def get_study_findings(cls, cursor, study: str) -> list[str]:
        return StudyAccess(cursor).get_study_findings()

    @classmethod
    def get_study_gnn_plot_configurations(cls, cursor, study: str) -> list[str]:
        return StudyAccess(cursor).get_study_gnn_plot_configurations()

    @classmethod
    def get_composite_phenotype_identifiers(cls, cursor) -> tuple[str, ...]:
        return sort(PhenotypesAccess(cursor).get_composite_phenotype_identifiers())

    @classmethod
    def get_phenotype_symbols(cls, cursor, study: str) -> tuple[PhenotypeSymbol, ...]:
        def key(symbol: PhenotypeSymbol) -> str:
            return symbol.handle_string
        return sort(PhenotypesAccess(cursor).get_phenotype_symbols(study), key=key)

    @classmethod
    def get_phenotype_criteria(cls, cursor, study: str, phenotype_symbol: str) -> PhenotypeCriteria:
        return PhenotypesAccess(cursor).get_phenotype_criteria(study, phenotype_symbol)

    @classmethod
    def retrieve_signature_of_phenotype(
        cls,
        cursor,
        phenotype_handle: str,
        study: str
    ) -> PhenotypeCriteria:
        channel_names = tuple(map(lambda r: r[0], PhenotypesAccess(cursor).get_channel_names(study)))
        components = StudyAccess(cursor).get_study_components(study)
        if phenotype_handle in channel_names:
            return PhenotypeCriteria(positive_markers=(phenotype_handle,), negative_markers=())
        if re.match(r'^\d+$', phenotype_handle):
            return PhenotypesAccess(cursor).get_phenotype_criteria_by_identifier(
                phenotype_handle,
                components.analysis,
            )
        if phenotype_handle != '':
            raise ValueError(f'Could not determine signature for phenotype with name/handle: {phenotype_handle}')
        return PhenotypeCriteria(positive_markers=(), negative_markers=())

    @classmethod
    def get_channel_names(cls, cursor, study: str) -> tuple[Channel, ...]:
        return sort(tuple(
            Channel(symbol=name, full_name=full_name)
            for name, full_name in PhenotypesAccess(cursor).get_channel_names(study)
        ), key=lambda c: c.symbol)

    @classmethod
    def get_important_cells(
        cls,
        cursor,
        study: str,
        plugin: str,
        datetime_of_run: str,
        plugin_version: str | None,
        cohort_stratifier: str | None,
        cell_limit: int = 100,
    ) -> set[int]:
        return GraphsAccess(cursor).get_important_cells(
            study,
            plugin,
            datetime_of_run,
            plugin_version,
            cohort_stratifier,
            cell_limit,
        )

    @classmethod
    def get_cells_data(cls, cursor, study: str, sample: str, **kwargs) -> tuple[CellsData, str | None]:
        return CellsAccess(cursor).get_cells_data(sample, **kwargs)

    @classmethod
    def get_cells_data_intensity(cls, cursor, study: str, sample: str, **kwargs) -> CellsData:
        return CellsAccess(cursor).get_cells_data_intensity(sample, **kwargs)

    @classmethod
    def get_cells_data_intensity_whole_study_subsample(cls, cursor, study: str, **kwargs) -> CellsData:
        return CellsAccess(cursor).get_cells_data_intensity_whole_study_subsample(study, **kwargs)

    @classmethod
    def get_cells_data_intensity_whole_study_subsample_binary_only(cls, cursor, study: str, **kwargs) -> CellsData:
        return CellsAccess(cursor).get_cells_data_intensity_whole_study_subsample_binary_only(study, **kwargs)

    @classmethod
    def get_ordered_feature_names(cls, cursor, study: str) -> BitMaskFeatureNames:
        return CellsAccess(cursor).get_ordered_feature_names()

    @classmethod
    def get_sample_names(cls, cursor, study: str) -> tuple[str, ...]:
        return sort(StudyAccess(cursor).get_specimen_names(study))

    @classmethod
    def has_umap(cls, cursor, study: str) -> bool:
        return StudyAccess(cursor).has_umap()

    @classmethod
    def get_channel_annotations(cls, cursor) -> ChannelAnnotations:
        groups = read_sql(
            '''
            SELECT name, color, channel_specific
            FROM channel_in_group cg
            JOIN channel_group g ON g.name=cg._group;
            ''',
            cursor.connection,
        )
        return ChannelAnnotations(channelGroups={
            name: ChannelGroupAnnotation(
                channels = sorted(list(set(group['channel_specific']))),
                color = color,
            )
            for (name, color), group in groups.groupby(['name', 'color'])
        })

    @classmethod
    def get_channel_aliases(cls, cursor) -> ChannelAliases:
        cursor.execute('SELECT channel_specific, alias FROM channel_alias;')
        rows = tuple(cursor.fetchall())
        return ChannelAliases(aliases=dict(rows))


def query() -> QueryCursor:
    return QueryCursor(QueryHandler)
