"""
Handles access, listing, and mapping between channel names in different
contexts like the study-specific context and an external reference atlas.

These are convenience functions to allow client workflows to abstract this
access.
"""
from os import environ as os_environ
from itertools import chain
from json import loads as json_loads
from pathlib import Path
from typing import Literal

from psycopg import sql as psycopg_sql
from psycopg import Cursor as PsycopgCursor

from smprofiler.db.exchange_data_formats.atlas_models import CellAtlasSource
from smprofiler.db.exchange_data_formats.atlas_models import InherenceAtlasAnnotatedChannel
from smprofiler.standalone_utilities.asset_loading import retrieve_from_library
from smprofiler.db.querying import QueryHandler
from smprofiler.db.accessors.feature_names import get_ordered_feature_names
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.credentials import retrieve_credentials_from_file
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class ChannelNamesOrganizer:
    database_config_file: Path
    atlas_source: CellAtlasSource
    db_cursor: DBCursor
    cursor: PsycopgCursor

    def __init__(self, database_config_file: Path, atlas_source: CellAtlasSource):
        self.database_config_file = database_config_file
        self.atlas_source = atlas_source

    def get_atlas_names_of_smprofiler_channels(self) -> tuple[str, ...]:
        """
        Just the list of all feature names which may appear in the atlas
        which can be corresponded with one of the SMProfiler database
        channel names.
        """
        return self._deduplicate(
            tuple(
                chain(*[
                    self._atlas_names(self._study_specific_to_atlas(study))
                    for study in self._get_studies()
                ])
            )
        )

    def get_inherence_and_atlas_annotated_study_channels(self, study: str) -> tuple[InherenceAtlasAnnotatedChannel, ...]:
        """
        Provides "inherence" (functional vs. identity) determination for
        all features for a given study, with the features' study-specific
        names and their atlas-specific names.
        """
        study_specific_names = self._study_specific_names(study)
        to_atlas = self._study_specific_to_atlas(study)
        atlas_specific_names = tuple(map(lambda key: to_atlas[key] if key in to_atlas else None, study_specific_names))
        inherence_assignments = self._get_inherence_annotations(study_specific_names)
        items = tuple(filter(
            lambda item: item[1] is not None and item[2] is not None,
            zip(study_specific_names, atlas_specific_names, inherence_assignments),
        ))
        return tuple(InherenceAtlasAnnotatedChannel(*item) for item in items)

    def get_inherence_and_atlas_annotated_study_channels_all(self) -> dict[str, tuple[InherenceAtlasAnnotatedChannel, ...]]:
        studies = self._get_studies()
        return {study: self.get_inherence_and_atlas_annotated_study_channels(study) for study in studies}

    def _get_inherence_annotations(self, study_specific_names: tuple[str, ...]) -> tuple[Literal['identity', 'functional'] | None, ...]:
        annotations = QueryHandler.get_channel_annotations(self.cursor)
        groups = annotations.channelGroups
        identity_channels: set = set(groups['identity'].channels)
        functional_channels = []
        for group_name, group in groups.items():
            if group_name != 'identity':
                functional_channels.extend(group.channels)

        def _assign_annotation(name: str) -> Literal['identity', 'functional'] | None:
            if name in identity_channels:
                return 'identity'
            if name in functional_channels:
                return 'functional'
            return None

        return tuple(map(_assign_annotation, study_specific_names))

    def _get_studies(self) -> tuple[str, ...]:
        self.cursor.execute('SELECT study FROM default_study_lookup.study_lookup;')
        studies = tuple(map(lambda row: row[0], self.cursor.fetchall()))
        return studies

    def _study_specific_to_atlas(self, study: str) -> dict[str, str]:
        study_specific_names = self._study_specific_names(study)
        smprofiler_names_normalizer = QueryHandler.get_channel_aliases(self.cursor).aliases
        manual_mapping_atlas_names = json_loads(
            retrieve_from_library('manual_mapping_atlas_names.json', 'db')
        )[self.atlas_source.value]
        virtual_channels = self._get_virtual_channels(study)

        def _study_specific_to_atlas_one_channel(channel: str) -> str | None:
            if channel in virtual_channels:
                return None
            candidates = [channel]
            if channel in smprofiler_names_normalizer:
                candidates.append(smprofiler_names_normalizer[channel])
            for candidate in candidates:
                if candidate in manual_mapping_atlas_names:
                    return manual_mapping_atlas_names[candidate]
            return channel

        def _not_none(value: str | None) -> bool:
            return value is not None

        return {
            study_specific: _study_specific_to_atlas_one_channel(study_specific)
            for study_specific in study_specific_names
            if _not_none(_study_specific_to_atlas_one_channel(study_specific))
        }

    def _get_virtual_channels(self, study: str) -> tuple[str, ...]:
        study_specific_names = self._study_specific_names(study)
        inherence_annotations = self._get_inherence_annotations(study_specific_names)
        return tuple(
            study_specific_name
            for study_specific_name, annotation
            in zip(study_specific_names, inherence_annotations)
            if annotation is None
        )

    def _study_specific_names(self, study: str) -> tuple[str, ...]:
        self._set_study(study)
        names = get_ordered_feature_names(self.cursor).names
        self._set_study(None)
        return tuple(map(lambda c: c.symbol, names))

    def _atlas_names(self, mapping: dict[str, str]) -> tuple[str, ...]:
        return tuple(mapping.values())

    def _deduplicate(self, items: tuple) -> tuple:
        return tuple(dict.fromkeys(items))

    def __enter__(self):
        if self.database_config_file is not None:
            credentials = retrieve_credentials_from_file(self.database_config_file)
            os_environ['SINGLE_CELL_DATABASE_HOST'] = credentials.endpoint
            os_environ['SINGLE_CELL_DATABASE_USER'] = credentials.user
            os_environ['SINGLE_CELL_DATABASE_PASSWORD'] = credentials.password
        self.db_cursor = DBCursor()
        self.cursor = self.db_cursor.__enter__()
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        if exception_value is not None:
            raise exception_value
        self.db_cursor.__exit__(None, None, None)
        return self

    def _set_study(self, study: str | None) -> None:
        if study is None:
            query = psycopg_sql.SQL('SET search_path TO {schema} ;').format(schema=psycopg_sql.Identifier('default_study_lookup'))
        else:
            schema = DBConnection.retrieve_study_schema(study, self.cursor)
            if schema is None:
                raise ValueError('Schema does not exist for study: %s', study)
            query = psycopg_sql.SQL('SET search_path TO {schema} ;').format(schema=psycopg_sql.Identifier(schema))
        self.cursor.execute(query)

