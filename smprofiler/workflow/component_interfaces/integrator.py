"""Interface for wrap-up task in Nextflow-managed workflow."""

from abc import ABC
from abc import abstractmethod


class Integrator(ABC): #pylint: disable=too-few-public-methods
    """Interface for wrap-up task in Nextflow-managed workflow."""
    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def calculate(self, **kwargs):
        pass
