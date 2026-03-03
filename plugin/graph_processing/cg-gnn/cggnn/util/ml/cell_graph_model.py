"""GNN that predicts a y-variable using cell graphs derived from tissue slide regions."""

from typing import Tuple, Union

from dgl import DGLGraph
from torch import FloatTensor

from ..ml.layers.constants import GNN_NODE_FEAT_IN
from .layers.mlp import MLP
from .base_model import BaseModel
from .layers.multi_layer_gnn import MultiLayerGNN


class CellGraphModel(BaseModel):
    """Cell Graph Model. Apply a GNN at the cell graph level."""

    def __init__(
        self,
        gnn_params: dict,
        classification_params: dict,
        node_dim: int,
        **kwargs
    ) -> None:
        """Construct a CellGraphModel model.

        Args:
            gnn_params: (dict) GNN configuration parameters.
            classification_params: (dict) classification configuration parameters.
            node_dim (int): Cell node feature dimension.
        """
        super().__init__(**kwargs)

        # 1- set class attributes
        self.node_dim = node_dim
        self.gnn_params = gnn_params
        self.readout_op = gnn_params['readout_op']
        self.classification_params = classification_params

        # 2- build cell graph params
        self._build_cell_graph_params()

        # 3- build classification params
        self._build_classification_params()

    def _build_cell_graph_params(self):
        """Build cell graph multi layer GNN."""
        self.cell_graph_gnn = MultiLayerGNN(
            input_dim=self.node_dim,
            **self.gnn_params
        )

    def _build_classification_params(self):
        """Build classification parameters."""
        if self.readout_op == "concat":
            emd_dim = self.gnn_params['output_dim'] * \
                self.gnn_params['num_layers']
        else:
            emd_dim = self.gnn_params['output_dim']

        self.pred_layer = MLP(
            in_dim=emd_dim,
            hidden_dim=self.classification_params['hidden_dim'],
            out_dim=self.num_classes,
            num_layers=self.classification_params['num_layers']
        )

    def forward(
        self,
        graph: Union[DGLGraph,
                     Tuple[FloatTensor, FloatTensor]]
    ) -> FloatTensor:
        """Forward pass.

        Args:
            graph (Union[dgl.DGLGraph, Tuple[FloatTensor, FloatTensor]]): Cell graph to process.

        Returns:
            FloatTensor: Model output.
        """

        # 1. GNN layers over the cell graph
        if isinstance(graph, DGLGraph):
            feats = graph.ndata[GNN_NODE_FEAT_IN]
            graph_embeddings = self.cell_graph_gnn(graph, feats)
        else:
            adj, feats = graph[0], graph[1]
            graph_embeddings = self.cell_graph_gnn(adj, feats)

        # 2. Run readout function
        out = self.pred_layer(graph_embeddings)

        return out

    def set_lrp(self, with_lrp):
        """Set LRP function."""
        self.cell_graph_gnn.set_lrp(with_lrp)
        self.pred_layer.set_lrp(with_lrp)

    def lrp(self, out_relevance_score):
        """Apply LRP function to out relevance score."""
        # lrp over the classification
        relevance_score = self.pred_layer.lrp(out_relevance_score)

        # lrp over the GNN layers
        relevance_score = self.cell_graph_gnn.lrp(relevance_score)

        return relevance_score
