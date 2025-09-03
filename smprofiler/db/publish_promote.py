"""Publish/promote a dataset collection from private to public."""

from typing import cast

from attr import define

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

@define
class PublisherPromoter:
    database_config_file: str
    collection: str | None = None

    def promote(self, collection: str) -> None:
        self.collection = collection
        self._check_is_collection_nonempty()
        self._whitelist_collection()

    def demote(self, collection: str) -> None:
        self.collection = collection
        self._check_is_collection_nonempty()
        self._unwhitelist_collection()

    def _check_is_collection_nonempty(self) -> None:
        def is_in_collection(study: str) -> bool:
            _, tag = StudyCollectionNaming.strip_token(study)
            return tag == self._get_collection()
        file = self.database_config_file
        with DBCursor(database_config_file=file, study=None) as cursor:
            update = f'SELECT study FROM study_lookup ;'
            cursor.execute(update)
            members = tuple(filter(is_in_collection, map(lambda row: row[0], cursor.fetchall())))
        if len(members) == 0:
            message = f'No studies are tagged with collection label "{self._get_collection()}".'
            logger.warning(message)

    def _whitelist_collection(self) -> None:
        file = self.database_config_file
        with DBCursor(database_config_file=file, study=None) as cursor:
            collection = self._get_collection()
            create = f'CREATE TABLE IF NOT EXISTS collection_whitelist ( collection VARCHAR(512) );'
            insert = f'INSERT INTO collection_whitelist (collection) VALUES ( %s ) ;'
            logger.debug(create)
            cursor.execute(create)
            logger.debug(insert % f"'{collection}'")
            cursor.execute(insert, (collection,))
        logger.info(f'Added "{collection}" to public-indicating whitelist.')

    def _unwhitelist_collection(self) -> None:
        file = self.database_config_file
        with DBCursor(database_config_file=file, study=None) as cursor:
            collection = self._get_collection()
            remove = f'DELETE FROM collection_whitelist WHERE collection=%s ;'
            logger.debug(remove % f"'{collection}'")
            cursor.execute(remove, (collection,))
        logger.info(f'Removed "{collection}" from public-indicating whitelist.')

    def _get_collection(self) -> str:
        return cast(str, self.collection)
