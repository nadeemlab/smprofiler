from typing import cast

from sqlite3 import connect
from sqlite3 import Cursor as SQLiteCursor
from sqlite3 import Connection as SQLiteConnection
import pickle

from smprofiler.standalone_utilities.chainable_destructable_resource import ChainableDestructableResource


class SQLiteConnectionManager(ChainableDestructableResource):
    connection: SQLiteConnection

    def __init__(self, handle: str):
        self.connection = connect(handle)

    def release(self) -> None:
        try:
            self.connection.close()
        except Exception:
            pass


class KeyValueStore(ChainableDestructableResource):
    """
    A key value store saved on disk or in memory using SQLite.
    The values should be pickle-serializable python objects.
    Supply ":memory" as the `handle` to use the in-memory version.
    """
    connection_manager: SQLiteConnectionManager
    read_only_db: SQLiteConnectionManager | None

    def __init__(self, handle: str = 'cache.sqlite3'):
        self.connection_manager = SQLiteConnectionManager(handle)
        self.read_only_db = SQLiteConnectionManager(':memory:')
        self.connection_manager.connection.backup(self.read_only_db.connection)
        self.cursor().execute('CREATE TABLE IF NOT EXISTS cache(key TEXT, contents BLOB);')
        self.add_subresource(self.connection_manager)
        self.add_subresource(self.read_only_db)

    def cursor(self) -> SQLiteCursor:
        return self.connection_manager.connection.cursor()

    def add(self, key: str, contents):
        self.drop(key)
        self.cursor().execute('INSERT INTO cache(key, contents) VALUES (?, ?);', (key, pickle.dumps(contents)))
        self.connection_manager.connection.commit()

    def drop(self, key: str) -> None:
        self._stop_using_read_only()
        self.cursor().execute('DELETE FROM cache WHERE key=?;', (key,))

    def _stop_using_read_only(self) -> None:
        cast(SQLiteConnectionManager, self.read_only_db).connection.close()
        self.read_only_db = None

    def lookup(self, key: str):
        if self.read_only_db is None:
            cursor = self.cursor()
        else:
            cursor = self.read_only_db.connection.cursor()
        cursor.execute('SELECT contents FROM cache WHERE key=?;', (key,))
        rows = cursor.fetchall()
        if len(rows) > 0:
            return pickle.loads(rows[0][0], encoding='bytes')
        return None


