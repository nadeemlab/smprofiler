from importlib.resources import as_file
from importlib.resources import files


def retrieve_from_library(filename: str, smprofiler_module: str, subpackage: str = 'assets', binary: bool = False) -> str | bytes:
    """
    Get contents of a data file stored in this library.
    - `smprofiler_module`: E.g. `atlas`, `workflow`.
    - `subpackage`: E.g. `assets.`
    - `binary`: If true, returns bytes rather than string.
    """
    filepath = files('.'.join(('smprofiler', smprofiler_module, subpackage))).joinpath(filename)
    with as_file(filepath) as path:
        if not binary:
            with open(path, 'rt', encoding='utf-8') as file:
                contents = file.read()
        else:
            with open(path, 'rb') as file:
                contents = file.read()
    return contents

