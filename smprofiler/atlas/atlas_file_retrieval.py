import re
from enum import Enum
from pathlib import Path
from typing import Iterable

import anndata as ad
from pandas import DataFrame
from tqdm import tqdm

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class CellAtlasSource(Enum):
    ALLEN_IMMUNE_HEALTH = 'Allen Immune Health 2025'


class AtlasFileRetrieval:
    """
    Provides access to reference cell atlas original files.
    """
    atlas_source: CellAtlasSource
    atlas_files_directory: Path

    def __init__(self, atlas_source: CellAtlasSource, atlas_files_directory: Path):
        self.atlas_source = atlas_source
        self.atlas_files_directory = atlas_files_directory

    def get_all_channels_from_atlas_files(self) -> list[str]:
        """
        Loads channel names from all atlas files to verify that they
        agree, then returns the channel names from one such file.
        """
        files = self._get_atlas_files()
        names_by_file = {}
        for file in files:
            names_from_file = self._load_atlas_file_variable_names(file)
            logger.info(f'Retrieving feature names from {file}... {len(names_from_file)} features/genes')
            names_by_file[file] = tuple(names_from_file)
        first_file, first_names = tuple(names_by_file.items())[0]
        for file, names in names_by_file.items():
            if tuple(names) != tuple(first_names):
                raise ValueError(f'Feature names differ between: {first_file} and {file}')
        return first_names

    def form_source_atlas_portions(self, atlas_feature_names: list[str]):
        """
        `yield`s DataFrames of the selected features, one block of cells at a time.
        """
        logger.info('Extracting cell data from ...')
        for file in self._get_atlas_files():
            logger.info(f'   ... {file}')
            for df in self._iterate_feature_subset(file, atlas_feature_names):
                yield df

    def _get_atlas_files(self) -> list[str]:
        if self.atlas_source == CellAtlasSource.ALLEN_IMMUNE_HEALTH:
            files = self.atlas_files_directory.glob('*.h5ad')
            files = self._filter_out_full_file(files)
        else:
            raise ValueError(f'Atlas source not supported: {self.atlas_source}')
        return files

    def _filter_out_full_file(self, files: Iterable[Path]) -> list[Path]:
        files = list(files)
        for file in files:
            if re.search('full', str(file)):
                logger.warning(f'File "{file}" not used, it is missing some features.')
        return list(filter(lambda file: not re.search('full', str(file)), files))

    def _load_atlas_file_variable_names(self, atlas_path: str) -> list[str]:
        adata = ad.read_h5ad(atlas_path, backed='r')
        variable_names = list(adata.var_names)
        adata.file.close()
        return variable_names

    def _iterate_feature_subset(self, atlas_path: str, features: list[str], chunk_size: int = 50000):
        adata = ad.read_h5ad(atlas_path, backed='r')
        column_indices = adata.var_names.get_indexer(features)
        if (column_indices < 0).any():
            raise ValueError(f'Some selected features missing from {atlas_path}.')
        n = adata.n_obs
        for start in tqdm(range(0, n, chunk_size)):
            end = min(start + chunk_size, n)
            block = adata.X[start:end][:, column_indices]
            if hasattr(block, 'toarray'):
                block = block.toarray()
            yield DataFrame(block, columns=features)
        adata.file.close()


