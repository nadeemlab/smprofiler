"""Abbreviations of common iteration patterns."""

from typing import TypeVar
from typing import Callable
from typing import Iterable


T = TypeVar('T')
S = TypeVar('S')

def tuple_map(func: Callable[[T], S], i: Iterable[T]) -> tuple[S, ...]:
    return tuple(map(func, i))

def tuple_filter(func: Callable[[T], bool], i: Iterable[T]) -> tuple[T, ...]:
    return tuple(filter(func, i))


