from pathlib import Path
from io import BytesIO
from os.path import exists

from pyarrow import Table as pyarrow_Table
from pyarrow.parquet import ParquetFile
from pyarrow.parquet import ParquetWriter

from smprofiler.atlas.channel_names_organizer import ChannelNamesOrganizer
from smprofiler.standalone_utilities.log_formats import colorized_logger

from atlas_file_retrieval import CellAtlasSource
from atlas_file_retrieval import AtlasFileRetrieval

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

    def __init__(
        self,
        atlas_source: CellAtlasSource = DEFAULT_ATLAS_SOURCE,
        atlas_files_directory: Path = Path('atlas_files'),
        database_config_file: str | None = None,
    ):
        if not exists(atlas_files_directory):
            raise ValueError('Directory %s for atlas files does not exist.', atlas_files_directory)
        self.atlas_file_retrieval = AtlasFileRetrieval(atlas_source, atlas_files_directory)
        self.database_config_file = database_config_file

    def extract(
        self,
        write_tables: bool = False,
        output_cell_atlas_filename: str = DEFAULT_ATLAS_SMALL,
    ) -> ParquetFile:
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
        atlas_extraction = self._get_atlas_extraction_parquet(atlas_names)
        if write_tables:
            writer = ParquetWriter(output_cell_atlas_filename)
            writer.write(atlas_extraction)
        return atlas_extraction

    def _get_atlas_extraction_parquet(self, atlas_names: list[str]) -> ParquetFile:
        writer = None
        in_memory = BytesIO()
        for df in self.atlas_file_retrieval.form_source_atlas_portions(atlas_names):
            table = pyarrow_Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = ParquetWriter(in_memory, table.schema)
            writer.write_table(table)
        if writer is not None:
            writer.close()
        return ParquetFile(in_memory)


if __name__ == '__main__':
    e = ExtractRelevantCellAtlas()
    e.extract(write_tables=True)

