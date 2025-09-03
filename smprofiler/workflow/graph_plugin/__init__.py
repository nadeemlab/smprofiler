"""Initialize workflow components for a graph plugin."""

from warnings import warn

from smprofiler.graphs.plugin_constants import PLUGIN_ALIASES
from smprofiler.workflow.common.workflow_module_exporting import WorkflowModules

TRUEY = ('true', 't', 'yes', 'y', '1')
FALSY = ('false', 'f', 'no', 'n', '0')

PLUGIN_DOCKER_IMAGES = {
    'cg-gnn': 'nadeemlab/smprofiler-cg-gnn',
    'graph-transformer': 'nadeemlab/smprofiler-graph-transformer',
}
PLUGIN_DOCKER_TAGS = {
    'cg-gnn': '0.0.3',
    'graph-transformer': '0.0.1',
}
CUDA_REQUIRED: tuple[str, ...] = ('graph-transformer', )
CPU_REQUIRED: tuple[str, ...] = ()


def process_inputs(params: dict[str, str | bool]) -> None:
    """Ensure that the necessary input parameters are specified."""
    plugin_name = _handle_required_config_entries(params)
    params['cuda'] = _determine_cuda_param(params.get('cuda'), plugin_name)
    for param in ('upload_importances',):
        params[param] = _determine_boolean_default_param(param, params.get(param))
    _handle_image_params(params, plugin_name)


def _handle_required_config_entries(params: dict[str, str | bool]) -> str:
    for param in ('plugin', 'graph_config_file'):
        if param not in params:
            raise ValueError(f'Must specify {param}.')
    for plugin, aliases in PLUGIN_ALIASES.items():
        if params['plugin'] in aliases:
            params['plugin'] = plugin
            break
    else:
        raise ValueError(
            f'Unrecognized plugin: {params["plugin"]}. Must be one of: '
            f'{", ".join(PLUGIN_ALIASES.keys())}.')
    return params['plugin']


def _determine_cuda_param(cuda: str | bool | None, plugin_name: str) -> bool:
    if isinstance(cuda, str):
        if cuda in TRUEY:
            cuda = True
        elif cuda in FALSY:
            cuda = False
        else:
            raise ValueError(f'cuda config entry must be a boolean, not {cuda}.')

    if plugin_name in CUDA_REQUIRED:
        if cuda is None:
            warn(f'{plugin_name} requires CUDA, but the cuda config setting wasn\'t '
                 'specified. Defaulting to True.')
            return True
        if cuda:
            return True
        else:
            raise ValueError(f'{plugin_name} requires CUDA, but it was set to False.')
    elif plugin_name in CPU_REQUIRED:
        if cuda:
            raise ValueError(f'{plugin_name} does not support CUDA, but it was set to True.')
        else:
            return False
    else:
        if cuda:
            return True
        else:
            return False


def _determine_boolean_default_param(
    param_name: str | None,
    param_value: str | bool | None,
    default_value: bool = False,
) -> bool:
    if param_value is None:
        return default_value
    if isinstance(param_value, bool):
        return param_value
    else:
        if param_value in TRUEY:
            return True
        elif param_value in FALSY:
            return False
        else:
            raise ValueError(f'{param_name} must be true or false if provided, not {param_value}.')


def _handle_image_params(params: dict[str, str | bool], plugin_name: str) -> None:
    if params['container_platform'] not in {'docker', 'singularity'}:
        raise ValueError(
            'For graph plugin workflows, the container_platform must be either `docker` or '
            f'`singularity`, not `{params["container_platform"]}`.')
    params['graph_plugin_image'] = f'{PLUGIN_DOCKER_IMAGES[plugin_name]}:' \
        f'{"cuda-" if (params["cuda"] and (plugin_name not in CUDA_REQUIRED)) else ""}' \
        f'{PLUGIN_DOCKER_TAGS[plugin_name]}'
    params['graph_plugin_singularity_run_options'] = '--nv' if \
        ((params['container_platform'] == 'singularity') and params['cuda']) else ''


components = WorkflowModules(
    assets_needed=[
        ('graph_generation', 'graph_generation.nf', False),
        ('graph_plugin', 'main.nf', True),
    ],
    config_section_required=True,
    process_inputs=process_inputs,
)
