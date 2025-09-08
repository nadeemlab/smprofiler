"""
A resource-release pattern to ensure cleanup without requiring the resource
user to explicitly call a cleanup function.
"""
from collections.abc import Iterable

class ChainableDestructableResource:
    """
    Implements a nested resource destructor pattern. The high-level item
    (compositionally containing the next-lower-level item, etc., recursively)
    can be used as a context manager, and all the release/destructor functions
    are called at the end of the context block.
    The intermediate objects do not need to be extensively modified, but need
    only override `get_subresources` to indicate which objects should be
    considered for release.
    """
    def get_subresources(self) -> Iterable['ResourceChainable']:
        return ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
        self.release_others()

    def release(self) -> None:
        pass

    def release_others(self) -> None:
        for resource in self.get_subresources():
            resource.__exit__()

