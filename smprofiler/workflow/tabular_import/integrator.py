"""The wrap-up task of the main data import workflow."""

from smprofiler.workflow.component_interfaces.integrator import Integrator


class TabularImportIntegrator(Integrator): #pylint: disable=too-few-public-methods
    """Wrap-up phase of the data import workflow. Currently no wrap-up is needed."""

    def __init__(self, **kwargs): # pylint: disable=unused-argument
        pass

    def calculate(self, **kwargs):
        pass
