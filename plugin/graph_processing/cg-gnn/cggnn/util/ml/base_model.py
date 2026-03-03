"""Base model for GNNs."""

from abc import abstractmethod

from torch import load
from torch.nn import Module


def get_number_of_classes(class_split):
    """Return number of classes given a class split."""
    return len(class_split.split('VS'))


class BaseModel(Module):
    """Base GNN model."""

    def __init__(
        self,
        class_split: str = None,
        num_classes: int = None
    ) -> None:
        """Construct a base model.

        Args:
            class_split (str): Class split. For instance in the BRACS dataset, one can specify
                               a 3-class split as:
                               "benign+pathologicalbenign+udhVSadh+feaVSdcis+malignant".
                               Defaults to None.
            num_classes (int): Number of classes. Used if class split is not provided.
                               Defaults to None.
        """
        super().__init__()

        assert not (class_split is None and num_classes is None), \
            "Please provide number of classes or class split."

        if class_split is not None:
            self.num_classes = get_number_of_classes(class_split)
        elif num_classes is not None:
            self.num_classes = num_classes
        else:
            raise ValueError(
                'Please provide either class split or number of classes. Not both.')

    def _build_classification_params(self):
        """Build classification parameters."""
        raise NotImplementedError('Implementation in subclasses.')

    def _load_checkpoint(self, checkpoint_path):
        self.load_state_dict(load(checkpoint_path))

    @abstractmethod
    def forward(self, graph):
        """Forward pass."""

    def set_forward_hook(self, module, layer):
        """Set forward hook to a layer."""
        module._modules.get(layer).register_forward_hook(self._forward_hook)

    def _forward_hook(self, module, input, output):
        """Activation hook."""
        self.latent_representation = output.data
