from pathlib import Path
from io import BytesIO

from pandas import DataFrame
from pyarrow import Table as pyarrow_Table
from pyarrow.parquet import ParquetFile
from pyarrow.parquet import ParquetWriter

from smprofiler.atlas.training import DEFAULT_ANNOTATIONS_API_URL
from smprofiler.atlas.application_databaes_feature_names import ApplicationDatabaseFeatureNames
from smprofiler.standalone_utilities.log_formats import colorized_logger

from channel_info_logging import AtlasChannelInfoLogging
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
    smprofiler_names_retrieval: ApplicationDatabaseFeatureNames

    def __init__(
        self,
        atlas_source: CellAtlasSource = DEFAULT_ATLAS_SOURCE,
        atlas_files_directory: Path = Path('atlas_files'),
        annotations_api_url: str = DEFAULT_ANNOTATIONS_API_URL,
    ):
        self.atlas_file_retrieval = AtlasFileRetrieval(atlas_source, atlas_files_directory)
        self.smprofiler_names_retrieval = ApplicationDatabaseFeatureNames(annotations_api_url)

    def extract(
        self,
        write_tables: bool = False,
        output_cell_atlas_filename: str = DEFAULT_ATLAS_SMALL,
    ) -> tuple[ParquetFile, DataFrame]:
        """
        Returns:
            * The extracted/subselected cell atlas as a ParquetFile table.
            * The "SMProfiler channel name" to "Atlas gene name" mapping dataframe.

        If `write_tables` is `True`, the return values are also written to file.
        """
        smprofiler_channels_to_atlas_df = self._get_smprofiler_channels_to_atlas_dataframe()
        if write_tables:
            smprofiler_channels_to_atlas_df.to_csv('smprofiler_channels_to_atlas.tsv', sep='\t', index=False)
        atlas_names = list(smprofiler_channels_to_atlas_df['Atlas gene name'].drop_duplicates())
        atlas_extraction = self._get_atlas_extraction_parquet(atlas_names)
        if write_tables:
            writer = ParquetWriter(output_cell_atlas_filename)
            writer.write(atlas_extraction)
        return atlas_extraction, smprofiler_channels_to_atlas_df

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

    def _get_smprofiler_channels_to_atlas_dataframe(self) -> DataFrame:
        smprofiler_channels_to_atlas, identity, functional, original_available = self._map_smprofiler_channels_to_atlas()
        df = DataFrame(smprofiler_channels_to_atlas.items(), columns=['SMProfiler channel name', 'Atlas gene name'])
        df = df.sort_values(by='SMProfiler channel name')
        return df

    def _map_smprofiler_channels_to_atlas(self) -> tuple[dict[str, str], list[str], list[str], int]:
        atlas_channels = self.atlas_file_retrieval.get_all_channels_from_atlas_files()
        identity, functional, aliases = self.smprofiler_names_retrieval.get_smprofiler_channels_and_aliases()
        AtlasChannelInfoLogging(atlas_channels, identity, functional).report_info()

        c = {}
        skipped = []
        for original, alias in aliases.items():
            if alias is None:
                print(f'Not using "{original}" because manual annotation manually omits it.')
                skipped.append(original)
                continue
            if original not in list(identity) + list(functional):
                raise ValueError(f'Feature name {original} in manual list of SMProfiler-normalizable names, but not among the features needed for...')
            if alias not in atlas_channels:
                raise ValueError(f'Feature name {alias} not occurring in atlas.')
            c[original] = alias
        for name in set(identity).union(functional).difference(c.keys()):
            if name in atlas_channels:
                c[name] = name
            else:
                if name not in skipped:
                    print(f'Channel {name} can not be associated to an atlas channel.')
        return c, sorted(list(set(identity).difference(skipped))), sorted(list(set(functional).difference(skipped))), len(identity) + len(functional)


if __name__ == '__main__':
    e = ExtractRelevantCellAtlas()
    e.extract(write_tables=True)
