"""Represent one job."""

from attrs import define
from psycopg import Notify
from psycopg import Connection as PsycopgConnection


@define(frozen=True)
class ComputationJobReference:
    """Represent one job."""
    feature_specification: int
    study: str
    sample: str
