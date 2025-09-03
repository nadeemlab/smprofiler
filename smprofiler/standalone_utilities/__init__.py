"""Simple standalone functions."""

from typing import Callable
from typing import Any

def sort(items: tuple[Any, ...] | list[str], key: Callable | None = None) -> tuple[Any, ...]:
    if key is None:
        return tuple(sorted(list(items)))
    return tuple(sorted(list(items), key=key))
