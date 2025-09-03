"""Wrapper class for describing the components of a given workflow."""

from typing import NamedTuple, Callable, Type

from smprofiler.workflow.component_interfaces import (
    JobGenerator,
    Initializer,
    CoreJob,
    Integrator,
)


class WorkflowModules(NamedTuple):
    """A wrapper object in which to list implementation classes comprising a workflow definition.
    
    Parameters
    ----------
    assets_needed: list[tuple[str, str, bool]]
        What Nextflow file assets the workflow needs. The tuple format is as follows:
            1. (str) The directory inside `smprofiler.workflow` that contains the asset
               (using period separators like in Python imports).
            2. (str) The filename of the asset.
            3. (bool) Whether this file is the workflow's entry point. (There can only be one of
               these.) This file will be copied into the main directory as `main.nf`, and all other
               assets will be copied to the subdirectory `nf_files` at configuration time. If you're
               using `include` in your Nextflow files, make sure to write them to reflect this
               runtime directory structure.
    generator: Type[JobGenerator] | None = None
    initializer: Type[Initializer] | None = None
    core_job: Type[CoreJob] | None = None
    integrator: Type[Integrator] | None = None
    config_section_required: bool = False
        Whether the workflow requires a custom config file section.
    process_inputs: Callable[[dict[str, str | bool]], None] = lambda _: None
        A function to process input parameters from the general and workflow-specific sections
        of the configuration file.
    image: str = 'nadeemlab/smprofiler'
        The name of the Docker Hub image to use for the workflow.
    """
    assets_needed: list[tuple[str, str, bool]]
    generator: Type[JobGenerator] | None = None
    initializer: Type[Initializer] | None = None
    core_job: Type[CoreJob] | None = None
    integrator: Type[Integrator] | None = None
    config_section_required: bool = False
    process_inputs: Callable[[dict[str, str | bool]], None] = lambda _: None
    image: str = 'nadeemlab/smprofiler'
