
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
        self.connection.close()


class SimpleFileCache(ChainableDestructableResource):
    """
    A key value store saved on disk using SQLite.
    The values should be pickle-serializable python objects.
    """
    connection_manager: SQLiteConnectionManager

    def __init__(self):
        self.connection_manager = SQLiteConnectionManager('cache.sqlite3')
        self.cursor().execute('CREATE TABLE IF NOT EXISTS cache(key TEXT, contents BLOB);')
        self.add_subresource(self.connection_manager)

    def cursor(self) -> SQLiteCursor:
        return self.connection_manager.connection.cursor()

    def add(self, key: str, contents):
        self.drop(key)
        self.cursor().execute('INSERT INTO cache(key, contents) VALUES (?, ?);', (key, pickle.dumps(contents)))
        self.connection_manager.connection.commit()

    def drop(self, key: str) -> None:
        self.cursor().execute('DELETE FROM cache WHERE key=?;', (key,))

    def lookup(self, key: str):
        cursor = self.cursor()
        cursor.execute('SELECT contents FROM cache WHERE key=?;', (key,))
        rows = cursor.fetchall()
        if len(rows) > 0:
            return pickle.loads(rows[0][0], encoding='bytes')
        return None


