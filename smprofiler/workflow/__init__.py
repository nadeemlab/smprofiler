"""
Each of the workflow subpackages contains the implementation details for one full pipeline.
They are:

1. A **job generator**. This writes the scripts that will run in the chosen runtime context
   (High-Performance Computing cluster, local, etc.).
2. The **core**. This represents one job's worth of computational work. This is ideally independent
   of file system and runtime context, such that a user of the library may use the main calculations
   to fit their own needs.
3. An **integrator**. This is the part of the pipeline that will run after any large-scale parallel
  jobs have completed. It is also potentially run *before* all such jobs have completed, to provide
  early final results on partial data.
4. The **computational design**. This is where idiosyncratic configuration parameters specific to
this pipeline are stored and managed.
"""

from importlib import import_module

from smprofiler.workflow.common.workflow_module_exporting import WorkflowModules

workflow_names_and_subpackages = {
    'tabular import': 'tabular_import',
    'graph generation': 'graph_generation',
    'graph plugin': 'graph_plugin',
}


def get_workflow_names() -> list[str]:
    return list(workflow_names_and_subpackages.keys())


def get_workflow(workflow_name: str) -> WorkflowModules:
    subpackage_name = workflow_names_and_subpackages[workflow_name]
    subpackage = import_module(f'.{subpackage_name}', __name__)
    return subpackage.components
