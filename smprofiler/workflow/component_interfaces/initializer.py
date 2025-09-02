"""Interface for the intializer job for the Nextflow-managed workflows."""
from abc import ABC
from abc import abstractmethod


class Initializer(ABC): #pylint: disable=too-few-public-methods
    """Interface for the intializer job for the Nextflow-managed workflows."""

    def __init__(self, **kwargs):
        pass

    @abstractmethod
    def initialize(self, **kwargs):
        pass
