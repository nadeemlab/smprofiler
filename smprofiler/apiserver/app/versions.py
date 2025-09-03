import re
from os.path import join
from pathlib import Path

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.exchange_data_formats.metrics import SoftwareComponentVersion
from smprofiler import __version__

def _get_postgres_version() -> str | None:
    try:
        with DBCursor() as cursor:
            cursor.execute('SELECT version();')
            text = tuple(cursor.fetchall())[0][0]
        match = re.search(r'^PostgreSQL (\d+).(\d+) ', text)
        if not match:
            return None
        return '.'.join(list(match.groups()))
    except EnvironmentError:
        return 'unavailable'

def retrieve_from_dependency_pins() -> dict[str, str]:
    source_path = Path(__file__).resolve()
    path = source_path.parent
    filename = join(path, 'requirements.txt')
    with open(filename, 'rt', encoding='utf-8') as file:
        lines = file.read().rstrip().split('\n')
    pins = {}
    for package in ('squidpy', 'pandas', 'numpy', 'scipy', 'scikit-learn', 'umap-learn'):
        for line in lines:
            match = re.search(rf'^{package}==(.*)$', line)
            if match:
                pins[package] = match.groups()[0]
    return pins

def get_software_component_versions() -> list[SoftwareComponentVersion]:
    V = SoftwareComponentVersion
    versions = []
    def append(*v):
        versions.append(V(
            component_name=v[0],
            format=v[1],
            source=v[2],
            relevant_to_reproducible_computation=v[3],
            version=v[4])
        )
    py = 'Python package'
    pypi = 'Python package index (PyPI)'
    pins = retrieve_from_dependency_pins()
    append('Squidpy', py, pypi, True, pins['squidpy'])
    append('Pandas', py, pypi, True, pins['pandas'])
    append('NumPy', py, pypi, True, pins['numpy'])
    append('SciPy', py, pypi, True, pins['scipy'])
    append('scikit-learn', py, pypi, True, pins['scikit-learn'])
    append('umap-learn', py, pypi, True, pins['umap-learn'])
    append('smprofiler', py, pypi, True, __version__)
    append('PostgreSQL', 'Database', 'Amazon RDS-managed', False, str(_get_postgres_version()))
    return versions
