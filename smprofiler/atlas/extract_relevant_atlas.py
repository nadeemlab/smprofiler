from pathlib import Path
from io import BytesIO
from os.path import exists
from typing import Any

from pyarrow import Table as pyarrow_Table
from pyarrow.parquet import ParquetFile
from pyarrow.parquet import ParquetWriter

from smprofiler.atlas.channel_names_organizer import ChannelNamesOrganizer
from smprofiler.standalone_utilities.log_formats import colorized_logger

from smprofiler.atlas.atlas_file_retrieval import CellAtlasSource
from smprofiler.atlas.atlas_file_retrieval import AtlasFileRetrieval

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
            * The extracted/subselected cell atlas as a ParquetFile table.

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
        report_parquet_attributes(p)

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


if __name__ == '__main__':
    e = ExtractRelevantCellAtlas()
    e.extract(write_tables=True)

