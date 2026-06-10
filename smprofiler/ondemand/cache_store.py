"""Cache storage abstraction for ondemand artifacts."""

from __future__ import annotations

from atexit import register as register_at_exit
from dataclasses import dataclass
import os
import re
from typing import Protocol
from typing import Any

from boto3 import client as boto3_client
from botocore.exceptions import ClientError
from psycopg import Connection as PsycopgConnection

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection

S3_CACHE_URI_ENV = "SMProfiler_S3_CACHE_URI"

class CacheStoreObjectNotFound(ValueError):
    def __init__(self, requested_key: Any, valid_keys: tuple[Any, ...]):
        message = f'Requested key "{requested_key}" not in store. Valid keys: {valid_keys}'
        super().__init__(message)


class CacheStore(Protocol):
    def put_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
        blob: bytes,
        *,
        drop_first: bool = False,
    ) -> None:
        ...

    def delete_blob(self, study: str | None, specimen: str | None, blob_type: str) -> None:
        ...

    def get_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
    ) -> bytes:
        ...

    def blob_exists(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
    ) -> bool:
        ...

class DatabaseCacheStore:
    connection: DBConnection

    def __init__(self, database_config_file: str | None, connection: DBConnection | None=None, register_cleanup: bool=True) -> None:
        if connection is not None:
            self.connection = connection
        else:
            self.connection = DBConnection(database_config_file=database_config_file)
            self.connection.__enter__()
        if register_cleanup:
            register_at_exit(self.cleanup)

    def cleanup(self) -> None:
        try:
            self.connection.__exit__(None, None, None)
        except Exception as e:
            print('Connection probably already closed.')
            raise e

    def put_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
        blob: bytes,
        *,
        drop_first: bool = False,
    ) -> None:
        specimen = self._preprocess_handle(specimen)
        with DBCursor(connection=self.connection, study=study) as cursor:
            if drop_first:
                drop = '''
                DELETE FROM
                ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s ;
                '''
                cursor.execute(drop, (specimen, blob_type))
            insert_query = '''
                INSERT INTO
                ondemand_studies_index (
                    specimen,
                    blob_type,
                    blob_contents)
                VALUES (%s, %s, %s) ;
            '''
            cursor.execute(insert_query, (specimen, blob_type, blob))
            cursor.close()

    def delete_blob(self, study: str | None, specimen: str | None, blob_type: str) -> None:
        specimen = self._preprocess_handle(specimen)
        with DBCursor(connection=self.connection, study=study) as cursor:
            delete_query = '''
                DELETE FROM ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s ;
            '''
            cursor.execute(delete_query, (specimen, blob_type))
            cursor.close()

    def get_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
    ) -> bytes:
        specimen = self._preprocess_handle(specimen)
        with DBCursor(connection=self.connection, study=study) as cursor:
            select_query = '''
                SELECT blob_contents FROM
                ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s ;
            '''
            cursor.execute(select_query, (specimen, blob_type))
            rows = tuple(cursor.fetchall())
            if len(rows) == 0:
                valid_keys = self._get_valid_keys(study)
                raise CacheStoreObjectNotFound((study, specimen, blob_type), valid_keys)
            return rows[0][0]

    def _get_valid_keys(self, study: str | None) -> tuple[Any, ...]:
        with DBCursor(connection=self.connection, study=study) as cursor:
            cursor.execute('SELECT specimen, blob_type FROM ondemand_studies_index;')
            return tuple(map(lambda row: (study, *row), tuple(cursor.fetchall())))

    def blob_exists(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
    ) -> bool:
        specimen = self._preprocess_handle(specimen)
        with DBCursor(connection=self.connection, study=study) as cursor:
            select_query = '''
                SELECT COUNT(*) FROM
                ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s ;
            '''
            cursor.execute(select_query, (specimen, blob_type))
            return tuple(cursor.fetchall())[0][0] >= 1

    def _preprocess_handle(self, specimen: str | None) -> str:
        if specimen is None:
            return ''
        return specimen


@dataclass(frozen=True)
class S3CacheLocation:
    bucket: str
    prefix: str


class S3CacheStore:
    def __init__(self, bucket: str, prefix: str) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip('/')
        self.client = boto3_client('s3')

    def put_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
        blob: bytes,
        *,
        drop_first: bool = False,
    ) -> None:
        key = self._build_key(study, specimen, blob_type)
        if drop_first:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=blob)

    def delete_blob(self, study: str | None, specimen: str | None, blob_type: str) -> None:
        key = self._build_key(study, specimen, blob_type)
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def get_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
    ) -> bytes:
        key = self._build_key(study, specimen, blob_type)
        return self.client.get_object(Bucket=self.bucket, Key=key)

    def blob_exists(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
    ) -> bool:
        key = self._build_key(study, specimen, blob_type)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                return False
            raise e
        return True

    def _build_key(self, study: str | None, specimen: str | None, blob_type: str) -> str:
        study_name = _sanitize_path_component(study or "unknown_study")
        specimen_name = _sanitize_path_component(specimen or "__none__")
        blob_name = _sanitize_path_component(blob_type)
        return f"{self.prefix}/{study_name}/{blob_name}/{specimen_name}.bin"


def _sanitize_path_component(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_")
    return sanitized if sanitized else "__none__"


def _parse_s3_cache_uri(uri: str) -> S3CacheLocation:
    match = re.match(r"^s3://([^/]+)/(.+)$", uri)
    if not match:
        raise ValueError(f"Invalid S3 cache URI: {uri}")
    bucket, prefix = match.groups()
    return S3CacheLocation(bucket=bucket, prefix=prefix)


def get_cache_store(database_config_file: str | None, cleanup_connection_on_exit: bool=True) -> CacheStore:
    cache_uri = os.environ.get(S3_CACHE_URI_ENV)
    if cache_uri:
        location = _parse_s3_cache_uri(cache_uri)
        return S3CacheStore(location.bucket, location.prefix)
    return DatabaseCacheStore(database_config_file, register_cleanup=cleanup_connection_on_exit)
