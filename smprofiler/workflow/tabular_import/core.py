"""The core/parallelizable functionality of the main data import workflow."""

from smprofiler.workflow.component_interfaces.core import CoreJob


class TabularImportCoreJob(CoreJob): #pylint: disable=too-few-public-methods
    """The parallelizable (per file) part of the import workflow. Currently this kind of a dummy
    implementation, beacuse a global view of the dataset is needed in order to parse it.
    """

    def _calculate(self):
        pass
