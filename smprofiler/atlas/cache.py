"""
Lightweight HTTP response cache, for convenience.
"""
from sqlite3 import Connection


class StandaloneSQLiteHTTPCache:
    cache_filename = '.temporary_http_response_cache.sqlite.db'

    @classmethod
    def cache_response(cls, url: str, response: bytes) -> None:
        """
        Overwrites value with key ``url`` if it exists.
        """
        with Connection(cls.cache_filename) as connection:
            cursor = connection.cursor()
            cursor.execute('CREATE TABLE IF NOT EXISTS cache(url VARCHAR, response BYTES)')
            cursor.execute('INSERT INTO cache VALUES (?, ?);', (url, response))

    @classmethod
    def retrieve_response(cls, url: str) -> bytes | None:
        with Connection(cls.cache_filename) as connection:
            cursor = connection.cursor()
            cursor.execute('SELECT response FROM cache WHERE url=?', (url,))
            rows = tuple(cursor.fetchall())
        if len(rows) == 0:
            return None
        return rows[0][0]


