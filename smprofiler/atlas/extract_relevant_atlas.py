from pathlib import Path
from io import BytesIO
from os.path import exists
import time

import numpy as np
from numpy.typing import NDArray
from pyarrow import Table as pyarrow_Table
from pyarrow.parquet import ParquetFile
from pyarrow.parquet import ParquetWriter
from pyarrow.parquet import read_schema

from smprofiler.atlas.channel_names_organizer import ChannelNamesOrganizer
from smprofiler.atlas.types import CellAtlasSource
from smprofiler.atlas.atlas_file_retrieval import AtlasFileRetrieval
from smprofiler.atlas.reporting import format_elapsed
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


DEFAULT_ATLAS_SOURCE = CellAtlasSource.ALLEN_IMMUNE_HEALTH
DEFAULT_ATLAS_SMALL = 'cell_atlas_small.parquet'


class ExtractRelevantCellAtlas:
    """
    Preprocesses data from one reference cell atlas, condensing it into one
    primary data artifact with only features relevant to given other datasets.
    """
    atlas_file_retrieval: AtlasFileRetrieval
    database_config_file: str | None
    extraction_path: Path

    def __init__(
        self,
        atlas_source: CellAtlasSource = DEFAULT_ATLAS_SOURCE,
        atlas_files_directory: Path = Path('atlas_files'),
        database_config_file: str | None = None,
        extraction_path: Path = Path(DEFAULT_ATLAS_SMALL)
    ):
        if not exists(atlas_files_directory):
            raise ValueError('Directory %s for atlas files does not exist.', atlas_files_directory)
        self.atlas_file_retrieval = AtlasFileRetrieval(atlas_source, atlas_files_directory)
        self.database_config_file = database_config_file
        self.extraction_path = extraction_path

    def extract(self, write_table: bool = False) -> ParquetFile:
        """
        Returns:
            * The extracted/subselected cell atlas as a ParquetFile.

        If `write_tables` is `True`, the return values are also written to file.
        """
        with ChannelNamesOrganizer(
            self.database_config_file,
            self.atlas_file_retrieval.atlas_source,
        ) as o:
            atlas_names = o.get_atlas_names_of_smprofiler_channels()
        atlas_extraction = self._get_atlas_extraction_parquet(atlas_names, write_table)
        return atlas_extraction

    def review_atlas_file(self) -> None:
        p = self.extraction_path
        if not p.exists():
            raise FileNotFoundError(f'Atlas parquet file not found: {p}')
        self._report_parquet_attributes(p)

    def _get_atlas_extraction_parquet(self, atlas_names: list[str], write_to_disk: bool) -> ParquetFile:
        writer = None
        disk_writer = None
        in_memory = BytesIO()
        for df in self.atlas_file_retrieval.form_source_atlas_portions(atlas_names):
            table = pyarrow_Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = ParquetWriter(in_memory, table.schema)
            writer.write_table(table)
            if write_to_disk:
                if disk_writer is None:
                    disk_writer = ParquetWriter(self.extraction_path, table.schema)
                disk_writer.write_table(table)
        if writer is not None:
            writer.close()
        if disk_writer is not None:
            disk_writer.close()
        return ParquetFile(in_memory)

    def _report_parquet_attributes(self, path: Path) -> None:
        size_mb = path.stat().st_size / (1024 ** 2)
        schema = read_schema(path)
        names = list(schema.names)
        n_rows = ParquetFile(path).metadata.num_rows
        logger.info(
            'Atlas parquet (%.1f MB): %s cells by %d genes - %s',
            size_mb, f'{n_rows:,}', len(names), path,
        )


class LoadFromExtraction:
    @classmethod
    def load(
        cls,
        parquet_path: Path,
        atlas_columns: list[str],
        max_cells: int | None = None,
        rng: np.random.Generator | None = None,
    ) -> NDArray:
        """
        Load specific gene columns from the atlas Parquet table.

        Args:
            parquet_path: path to cell_atlas_small.parquet
            atlas_columns: atlas gene names to load (may contain duplicates when
                several SMProfiler channels share one atlas gene; each entry
                becomes its own output column)
            max_cells: if set, randomly sample this many cells
            rng: random number generator for sampling

        Returns:
            numpy.NDArray of shape (n_cells, len(atlas_columns)).
        """
        logger.info('Loading %d atlas columns from parquet: %s', len(atlas_columns), atlas_columns)
        t0 = time.monotonic()

        unique_columns = list(set(atlas_columns))
        parquet_file = ParquetFile(parquet_path)
        number_cells = parquet_file.metadata.num_rows
        table = parquet_file.read(columns=unique_columns)

        if max_cells and number_cells > max_cells:
            if rng is None:
                rng = np.random.default_rng(42)
            indices = np.sort(rng.choice(number_cells, size=max_cells, replace=False))
            table = table.take(indices)
            logger.info(
                'Sampling %s / %s cells from atlas (%.1f%%)…',
                f'{max_cells:,}', f'{number_cells:,}', 100 * max_cells / number_cells,
            )
        else:
            logger.info('Loading all %s cells from atlas…', f'{number_cells:,}')

        column_values = {
            name: table.column(name).to_numpy(zero_copy_only=False).astype(np.float32)
            for name in unique_columns
        }
        X = np.column_stack([column_values[name] for name in atlas_columns]).astype(np.float32)

        logger.info(
            'Atlas data loaded in %s - shape %s (%.1f MB)',
            format_elapsed(time.monotonic() - t0),
            X.shape,
            X.nbytes / (1024 ** 2),
        )
        return X

