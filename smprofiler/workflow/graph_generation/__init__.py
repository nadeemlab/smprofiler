"""Initialize graph generation workflow components."""

from smprofiler.workflow.common.workflow_module_exporting import WorkflowModules


def process_inputs(params: dict[str, str | bool]) -> None:
    """Ensure that the necessary input parameters are specified."""
    for param in ('graph_config_file', ):
        if param not in params:
            raise ValueError(f'Must specify {param}.')


components = WorkflowModules(
    assets_needed=[
        ('graph_generation', 'graph_generation.nf', False),
        ('graph_generation', 'main.nf', True),
    ],
    config_section_required=True,
    process_inputs=process_inputs,
)
