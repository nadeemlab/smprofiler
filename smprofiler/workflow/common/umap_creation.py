"""UMAP dimensional reduction."""
import warnings
import brotli
from typing import cast

from pandas import DataFrame
import pandas.errors as pd_errors
from umap import UMAP
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import QuantileTransformer

from smprofiler.ondemand.compressed_matrix_handling import compress_bitwise_to_int
from smprofiler.ondemand.compressed_matrix_handling import CompressedMatrixHandling
from smprofiler.ondemand.defaults import FEATURE_MATRIX_WITH_INTENSITIES
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.db.database_connection import DBCursor
from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_SPEC1
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_SPEC2
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE_COMPRESSED
from smprofiler.standalone_utilities.log_formats import colorized_logger

warnings.simplefilter(action='ignore', category=pd_errors.PerformanceWarning)
warnings.filterwarnings(action='ignore', message='n_jobs value 1 overridden to 1 by setting random_state. Use no seed for parallelism.')

logger = colorized_logger(__name__)

UMAP_POINT_LIMIT = 40000

class NoContinuousIntensityDataError(ValueError):
    pass


class UMAPCreator:
    database_config_file: str | None
    study: str

    def __init__(self, database_config_file: str | None, study: str):
        self.database_config_file = database_config_file
        self.study = study

    def create_from_dense_frames(
        self,
        continuous: DataFrame,
        discrete: DataFrame,
        ordered_symbols: tuple[str, ...],
    ) -> None:
        if all(continuous.isna().all()):
            raise NoContinuousIntensityDataError
        reduced = UMAPReducer.create_2d_point_cloud(continuous)
        self._write_to_database(reduced, discrete, continuous, ordered_symbols=ordered_symbols)

    @staticmethod
    def sparse_to_dense(sparse_df: DataFrame, values_column: str) -> DataFrame:
        logger.info(f'Converting sparse matrix to dense matrix. ({values_column})')
        dense_df = sparse_df.pivot(index='structure', columns=['channel'], values=[values_column])
        logger.info(f'Dense matrix ({values_column}) has size: {dense_df.shape}')
        return dense_df

    def validate_all_structures_have_same_channels(self, df) -> bool:
        if not (df.channel.value_counts() == len(df.structure.unique())).all():
            message = 'Cannot create a UMAP representation for study %s because given objects \
            have different sets of targets provided. Hence object representations have different \
            dimension which is incompatible with UMAP dimension reduction.'
            logger.error(message, self.study)
            raise ValueError(message % self.study)
        return True

    def _write_to_database(
        self,
        reduced,
        discrete: DataFrame,
        continuous: DataFrame,
        ordered_symbols: tuple[str, ...],
    ) -> None:
        data_array = self._create_data_array(discrete, ordered_symbols=ordered_symbols)
        centroids = dict(tuple(
            zip(tuple(discrete.index.astype(int)), tuple(zip(reduced[:,0], reduced[:,1])))
        ))

        phenotype_bytes = {cell_id: integer.to_bytes(8, 'little') for cell_id, integer in data_array.items()}
        raw = CompressedMatrixHandling.zip_location_and_phenotype_data(centroids, phenotype_bytes)
        compressed = brotli.compress(raw, quality=11, lgwin=24)
        cache_store = get_cache_store(self.database_config_file)
        self._drop_existing_umap_cache(cache_store)
        cache_store.put_blob(self.study, VIRTUAL_SAMPLE, VIRTUAL_SAMPLE_COMPRESSED, compressed)
        logger.info('Saved UMAP centroids and feature matrix combo.')
        logger.info('Saving UMAP specialized intensities matrix.')
        intensities = self._normalize_column_order(continuous, 'quantity', ordered_symbols=list(ordered_symbols))
        intensities_dict = {int(i): tuple(float(intensities.loc[i, c]) for c in intensities.columns) for i in intensities.index}
        cache_store.put_blob(
            self.study,
            VIRTUAL_SAMPLE,
            FEATURE_MATRIX_WITH_INTENSITIES,
            CompressedMatrixHandling.form_intensities_compressed_blob(intensities_dict),
        )
        logger.info('Done.')

    def _drop_existing_umap_cache(self, cache_store):
        logger.info('  Dropping existing UMAP cache blobs.')
        cache_store.delete_blob(self.study, VIRTUAL_SAMPLE_SPEC1[0], VIRTUAL_SAMPLE_SPEC1[1])
        cache_store.delete_blob(self.study, VIRTUAL_SAMPLE_SPEC2[0], VIRTUAL_SAMPLE_SPEC2[1])
        cache_store.delete_blob(self.study, VIRTUAL_SAMPLE, VIRTUAL_SAMPLE_COMPRESSED)
        cache_store.delete_blob(self.study, VIRTUAL_SAMPLE, FEATURE_MATRIX_WITH_INTENSITIES)
        logger.info('  Done.')

    def _normalize_column_order(
        self,
        df: DataFrame,
        modifier: str,
        ordered_symbols: list[str] | None = None,
    ) -> DataFrame:
        if ordered_symbols is None:
            with DBCursor(database_config_file=self.database_config_file, study=self.study) as cursor:
                ordered = CellsAccess(cursor).get_ordered_feature_names()
            ordered_symbols = [n.symbol for n in ordered.names]
        symbols = [(modifier, n) for n in ordered_symbols]
        logger.info(f'Using feature order: {[s[1] for s in symbols]}')
        df_ordered = cast(DataFrame, df[symbols])
        return df_ordered.sort_index()

    def _create_data_array(self, df: DataFrame, ordered_symbols: tuple[str, ...]) -> dict[int, int]:
        df_ordered = self._normalize_column_order(df, 'discrete_value', ordered_symbols=list(ordered_symbols))
        data_array = {}
        for i, (_, row) in enumerate(df_ordered.iterrows()):
            binary = row.astype(int).to_numpy()
            data_array[i] = compress_bitwise_to_int(binary)
        return data_array


class UMAPReducer:
    """From dataframe create UMAP-reduced point clouds."""
    @staticmethod
    def create_2d_point_cloud(dense_df: DataFrame):
        continuous_only = UMAPReducer.drop_discrete_features(dense_df)
        normalized = UMAPReducer.preprocess_univariate_adjustments(continuous_only)
        reduced = UMAPReducer.umap_reduce_to_2d(normalized)
        reduced_scaled = UMAPReducer.scale_up(reduced)
        return reduced_scaled

    @staticmethod
    def drop_discrete_features(df: DataFrame) -> DataFrame:
        non_droppables = set(map(lambda c: len(set(df[c])) > 2, df.columns))
        if len(non_droppables) == 0:
            raise NoContinuousIntensityDataError
        ordered = [c for c in df.columns if c in non_droppables]
        return cast(DataFrame, df[ordered])

    @staticmethod
    def preprocess_univariate_adjustments(df):
        pipeline = make_pipeline(SimpleImputer(strategy="mean"), QuantileTransformer())
        return pipeline.fit_transform(df.copy())

    @staticmethod
    def umap_reduce_to_2d(array):
        manifold = UMAP(random_state=99, min_dist=0.2).fit(array)
        return manifold.transform(array)

    @staticmethod
    def scale_up(array):
        first = tuple(zip(array[0:5,0], array[0:5,1]))
        logger.info(f'First few points: {first}')
        size_x = max(array[:,0])
        size_y = max(array[:,1])
        scale = 5000 / min(size_x, size_y)
        scaled = scale * array
        first = tuple(zip(scaled[0:5,0], scaled[0:5,1]))
        logger.info(f'After scaling: {first}')
        return scaled

