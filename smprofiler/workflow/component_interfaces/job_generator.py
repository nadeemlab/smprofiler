"""Interface for parallelizable job manifest generation."""
from abc import ABC
from abc import abstractmethod


class JobGenerator(ABC): #pylint: disable=too-few-public-methods
    """Interface for parallelizable job manifest generation."""

    @abstractmethod
    def write_job_specification_table(self, job_specification_table_filename):
        pass
