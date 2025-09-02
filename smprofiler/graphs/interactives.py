"""Create and save interactive plots."""

from os import makedirs
from os.path import join
from typing import DefaultDict

from tqdm import tqdm
from networkx import Graph, from_scipy_sparse_array, compose, get_node_attributes  # type: ignore
from bokeh.models import (
    Circle,
    MultiLine,
    WheelZoomTool,
    HoverTool,
    CustomJS,
    Select,
    ColorBar,
)
from bokeh.plotting import figure, from_networkx
from bokeh.transform import linear_cmap
from bokeh.palettes import YlOrRd8
from bokeh.layouts import row
from bokeh.io import output_file, save

from smprofiler.graphs.util import GraphData, HSGraph


def plot_interactives(
    graphs_data: list[GraphData],
    feature_names: list[str],
    out_directory: str,
    merge_rois: bool = False,
) -> None:
    """Create bokeh interactive plots for all graphs in the out_directory."""
    out_directory = join(out_directory, 'interactives')
    makedirs(out_directory, exist_ok=True)
    graphs_to_plot: dict[str, list[HSGraph]] = DefaultDict(list)
    for g in graphs_data:
        graphs_to_plot[g.specimen if merge_rois else g.name].append(g.graph)
    for name, hs_graphs in tqdm(graphs_to_plot.items()):
        graphs = [_convert_hs_graph_to_networkx(graph, feature_names) for graph in hs_graphs]
        _make_bokeh_graph_plot(_stich_specimen_graphs(graphs), feature_names, name, out_directory)


def _make_bokeh_graph_plot(
    graph: Graph,
    feature_names: list[str],
    graph_name: str,
    out_directory: str,
) -> None:
    """Create bokeh interactive graph visualization."""
    graph_name = graph_name.split('/')[-1]
    output_file(join(out_directory, graph_name + '.html'), title=graph_name)
    f = figure(match_aspect=True, tools=['pan', 'wheel_zoom', 'reset'], title=graph_name)
    f.toolbar.active_scroll = f.select_one(WheelZoomTool)
    # colors nodes according to importance by default
    mapper = linear_cmap('importance', palette=YlOrRd8[::-1], low=0, high=1)
    plot = from_networkx(graph, {
        i_node: dat for i_node, dat in get_node_attributes(graph, 'centroid').items()
    })
    plot.node_renderer.glyph = Circle(
        radius='radius',
        fill_color=mapper,
        line_width=.1,
        fill_alpha=.7,
    )
    plot.edge_renderer.glyph = MultiLine(line_alpha=0.2, line_width=.5)

    # Add color legend to right of plot
    colorbar = ColorBar(color_mapper=mapper['transform'], width=8)
    f.add_layout(colorbar, 'right')

    # Define data that shows when hovering over a node/cell
    hover = HoverTool(tooltips="h. structure: $index", renderers=[plot.node_renderer])
    hover.callback = CustomJS(
        args=dict(hover=hover, source=plot.node_renderer.data_source),
        code='const feats = ["' + '", "'.join(feature_names) + '"];' +
        """
        if (cb_data.index.indices.length > 0) {
            const node_index = cb_data.index.indices[0];
            const tooltips = [['h. structure', '$index']];
            for (const feat_name of feats) {
                if (source.data[feat_name][node_index]) {
                    tooltips.push([`${feat_name}`, `@{${feat_name}}`]);
                }
            }
            hover.tooltips = tooltips;
        }
    """,
    )
    # ${blah} evaluates blah in javascript, so `@{${blah}}` comes out to "@{evaluated_blah}"
    # @{Some Thing} is how to refer to a column named "Some Thing" in Bokeh's data source

    # Add interactive dropdown to change why field nodes are colored by
    color_select = Select(title='Color by property', value='importance',
                          options=['importance'] + feature_names)
    color_select.js_on_change('value', CustomJS(
        args=dict(source=plot.node_renderer.data_source, cir=plot.node_renderer.glyph),
        code="""
            const field = cb_obj.value;
            cir.fill_color.field = field;
            source.change.emit();
        """,
    ))

    # Place components side-by-side and save to file
    layout = row(f, color_select)
    f.renderers.append(plot)
    f.add_tools(hover)
    save(layout)


def _convert_hs_graph_to_networkx(hs_graph: HSGraph, feature_names: list[str]) -> Graph:
    """Convert HSGraph to networkx graph for plotting interactive."""
    if hs_graph.importances is None:
        raise ValueError(
            'Importance scores not yet found. Calculate them and place them in hs_graph.importances.'
        )
    graph_networkx = from_scipy_sparse_array(hs_graph.adj)
    for i_g in range(hs_graph.node_features.shape[0]):
        feats = hs_graph.node_features[i_g, :]
        for j, feat in enumerate(feature_names):
            graph_networkx.nodes[i_g][feat] = feats[j]
        graph_networkx.nodes[i_g]['importance'] = hs_graph.importances[i_g]
        graph_networkx.nodes[i_g]['radius'] = hs_graph.importances[i_g]*10
        graph_networkx.nodes[i_g]['centroid'] = tuple(hs_graph.centroids[i_g, :])
    return graph_networkx


def _stich_specimen_graphs(graphs: list[Graph]) -> Graph:
    """Stitch graphs together."""
    if len(graphs) == 0:
        raise ValueError("Must have at least one graph to stitch.")
    if len(graphs) == 1:
        return graphs[0]
    graph_stitched = graphs[0]
    for graph in graphs[1:]:

        # Check for node overlaps and find the max importance score
        overlap_importance: dict[int, float] = {
            i: max(graph_stitched.nodes[i]['importance'], graph.nodes[i]['importance'])
            for i in set(graph_stitched.nodes).intersection(graph.nodes)
        }

        # Stich the next graph into the collected graph
        graph_stitched = compose(graph_stitched, graph)

        # Overwrite the max importance score.
        for i, importance in overlap_importance.items():
            graph_stitched.nodes[i]['importance'] = importance

    return graph_stitched
