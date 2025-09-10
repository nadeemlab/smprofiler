"""
A resource-release pattern to ensure cleanup without requiring the resource
user to explicitly call a cleanup function.
"""

class ChainableDestructableResource:
    """
    Implements a nested resource destructor pattern.
    For a number of nested resources (the nesting being explicitly declared),
    an item at any level can be used as a context manager in which all
    subresources are cleaned up recursively at the end.
    The intermediate objects do not need to be extensively modified, but need
    only use `add_subresource` to indicate which objects should be considered
    for release.

    Example usage:
    ```py
    class AtomicResource:
        def work_on(self):
            print('Inner atomic resource was worked on.')

        def close(self):
            print('Inner atomic resource was closed.')

    class Intermediate(ChainableDestructableResource):
        def __init__(self):
            self.y = AtomicResource()

        def release(self) -> None:
            self.y.close()

    class HighLevel(ChainableDestructableResource):
        def __init__(self):
            self.x = Intermediate()
            self.add_subresource(self.x)

    with HighLevel() as r:
        r.x.y.work_on()
    # r.x.y.close() is called

    with Intermediate() as r:
        r.y.work_on()
    # r.y.close() is called
    ```
    """
    _subresources: list['ChainableDestructableResource']

    def add_subresource(self, resource: 'ChainableDestructableResource'):
        """
        Use this method to indicate which resources should be triggered to clean up
        when this given resource is cleaning up.
        """
        self._ensure_initialized()
        self._subresources.append(resource)

    def release(self) -> None:
        """
        If this given resource has specific cleanup to do, in addition to just
        delegating cleanup to subresources, override this method to do so. For example,
        if the class is supposed to wrap a database connection, this method could
        call `connection.close()`.
        """
        pass

    def _ensure_initialized(self) -> None:
        if not hasattr(self, '_subresources'):
            self._subresources = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._release()

    def _release(self) -> None:
        self.release()
        self._release_others()

    def _release_others(self) -> None:
        self._ensure_initialized()
        for resource in self._get_subresources():
            resource.__exit__()

    def _get_subresources(self) -> list['ChainableDestructableResource']:
        return self._subresources



