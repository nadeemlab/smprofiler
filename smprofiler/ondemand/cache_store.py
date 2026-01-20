"""Cache storage abstraction for ondemand artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from typing import Protocol

from boto3 import client as boto3_client

from smprofiler.db.database_connection import DBCursor


S3_CACHE_URI_ENV = "SMProfiler_S3_CACHE_URI"


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


class DatabaseCacheStore:
    def __init__(self, database_config_file: str | None) -> None:
        self.database_config_file = database_config_file

    def put_blob(
        self,
        study: str | None,
        specimen: str | None,
        blob_type: str,
        blob: bytes,
        *,
        drop_first: bool = False,
    ) -> None:
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
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
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
            delete_query = '''
                DELETE FROM ondemand_studies_index
                WHERE specimen=%s AND blob_type=%s ;
            '''
            cursor.execute(delete_query, (specimen, blob_type))
            cursor.close()


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


def get_cache_store(database_config_file: str | None) -> CacheStore:
    cache_uri = os.environ.get(S3_CACHE_URI_ENV)
    if cache_uri:
        location = _parse_s3_cache_uri(cache_uri)
        return S3CacheStore(location.bucket, location.prefix)
    return DatabaseCacheStore(database_config_file)
