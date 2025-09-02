"""Standalone functions encapsulating some of the boilerplate in common DB accessors."""
from typing import cast


class GetSingleResult:
    """Standalone functions encapsulating some of the boilerplate in common DB accessors."""
    @classmethod
    def row(cls, cursor, query: str, parameters: tuple | None=None) -> tuple | None:
        """"Optimistically" return the first result row for a given query."""
        if not parameters is None:
            cursor.execute(query, parameters)
        else:
            cursor.execute(query)
        rows = cursor.fetchall()
        if len(rows) > 0:
            return tuple(rows[0])
        return None

    @classmethod
    def integer(cls, *args, **kwargs) -> int:
        """"Optimistically" get a single integer from a query, or else provide a given backup value.
        """
        return cast(int, cls._value(*args, **kwargs))

    @classmethod
    def string(cls, *args, **kwargs) -> str:
        """"Optimistically" get a single string from a query, or else provide a given backup value.
        """
        return cast(str, cls._value(*args, **kwargs))

    @classmethod
    def _value(cls,
            cursor,
            query: str,
            parameters: tuple | None=None,
            or_else_value='',
        ) -> str | int:
        if not parameters is None:
            cursor.execute(query, parameters)
        else:
            cursor.execute(query)
        rows = cursor.fetchall()
        if len(rows) > 0:
            return rows[0][0]
        return or_else_value
