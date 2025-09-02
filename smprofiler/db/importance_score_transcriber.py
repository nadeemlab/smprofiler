"""Ingest importance scores and upload them to the local database."""

from datetime import datetime

from pandas import (
    DataFrame,
    read_sql,
    to_datetime,
    Timestamp,
)
from psycopg import Connection as PsycopgConnection

from smprofiler.util import STRFTIME_FORMAT
from smprofiler.graphs.plugin_constants import PLUGIN_ALIASES
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.create_data_analysis_study import DataAnalysisStudyFactory
from smprofiler.workflow.common.export_features import ADIFeaturesUploader
from smprofiler.db.describe_features import get_feature_description
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def transcribe_importance(
    df: DataFrame,
    database_config_file: str,
    study: str,
    plugin_used: str,
    datetime_of_run: str | datetime | Timestamp,
    plugin_version: str | None = None,
    cohort_stratifier: str | None = None,
    per_specimen_selection_number: int = 1000,
) -> None:
    """Upload importance score output from a cg-gnn instance to the local db.

    Parameters:
        df: DataFrame
            One column, `importance`, indexed by `histological_structure`.
        database_config_file: str
            Path to the database configuration file.
        study: str
        plugin_used: str
            Name of the classification model that produced these importance scores.
        datetime_of_run: str | datetime
            Datetime the classification model was run to produce these importance scores.
        plugin_version: str | None = None
            Version of the classification model that produced these importance scores.
        cohort_stratifier: str | None = None
            Name of the classification cohort variable the data was split on to create the data used
            to generate the importance scores.
        per_specimen_selection_number: int = 1000
            Grab this many of the most important cells from each specimen (or fewer if there aren't
            enough cells in the specimen).
    """
    for plugin_name, plugin_aliases in PLUGIN_ALIASES.items():
        if plugin_used.lower() in plugin_aliases:
            plugin_used = plugin_name
            break
    else:
        ValueError(f"Unrecognized plugin name: {plugin_used}")
    if isinstance(datetime_of_run, str):
        datetime_of_run = to_datetime(datetime_of_run)
    if plugin_version is None:
        plugin_version = ''
    if cohort_stratifier is None:
        cohort_stratifier = ''

    with DBConnection(database_config_file=database_config_file, study=study) as connection:
        data_analysis_study = DataAnalysisStudyFactory(
            connection,
            study,
            'cell importance',
        ).create()
        _add_slide_column(connection, df)
        df_most_important = _group_and_filter(df, per_specimen_selection_number)
        _upload(
            df_most_important,
            connection,
            data_analysis_study,
            plugin_used,
            datetime_of_run,
            plugin_version,
            cohort_stratifier,
        )


def _add_slide_column(connection: PsycopgConnection, df: DataFrame) -> None:
    lookup = read_sql("""
        SELECT
            hsi.histological_structure,
            sdmp.specimen
        FROM histological_structure_identification hsi
            JOIN data_file df
                ON hsi.data_source=df.sha256_hash
            JOIN specimen_data_measurement_process sdmp
                ON df.source_generation_process=sdmp.identifier
        ;
    """, connection)
    lookup['histological_structure'] = lookup['histological_structure'].astype(int)
    reindexed = lookup.set_index('histological_structure')
    df['specimen'] = reindexed.loc[df.index, 'specimen']


def _group_and_filter(df: DataFrame, filter_number: int) -> DataFrame:
    ordered = df.sort_values(by='importance', ascending=False)
    ordered['importance_order'] = 1
    grouped = ordered.groupby('specimen')
    ranks = grouped['importance_order'].cumsum()
    df_most_important = \
        grouped.head(filter_number).drop('importance_order', axis=1).join(ranks, how='left')
    return df_most_important


def _upload(
    df: DataFrame,
    connection: PsycopgConnection,
    data_analysis_study: str,
    plugin_used: str,
    datetime_of_run: datetime,
    plugin_version: str,
    cohort_stratifier: str,
) -> None:
    importance_score_set_indexer = (
        plugin_used,
        datetime_of_run.strftime(STRFTIME_FORMAT),
        plugin_version,
        cohort_stratifier,
    )
    with ADIFeaturesUploader(
        connection,
        data_analysis_study=data_analysis_study,
        derivation_and_number_specifiers=(
            get_feature_description("gnn importance score"),
            len(importance_score_set_indexer),
        ),
    ) as feature_uploader:
        for histological_structure, row in df.iterrows():
            feature_uploader.stage_feature_value(
                importance_score_set_indexer,
                str(histological_structure),
                row['importance_order'],
            )
