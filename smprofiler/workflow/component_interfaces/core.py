"""Interface for the parallelizable jobs of a given workflow."""

from abc import ABC
from abc import abstractmethod

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class CoreJob(ABC): #pylint: disable=too-few-public-methods
    """Interface for the parallelizable jobs of a given workflow."""

    @abstractmethod
    def _calculate(self):
        pass

    def calculate(self):
        """The main calculation of this job, to be called by pipeline orchestration."""
        logger.info('Started core calculator job.')
        self._calculate()
        logger.info('Completed core calculator job.')
