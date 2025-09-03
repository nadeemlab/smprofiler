"""Low-level calculations of squidpy metrics."""

from typing import Any
from typing import cast
from typing import (
    TYPE_CHECKING,
    Literal,
)
from warnings import filterwarnings

from numpy.typing import NDArray
from numpy import isnan
from numpy import inner
from numpy import sum as np_sum
from pandas import DataFrame, Series

filterwarnings(action='ignore', category=SyntaxWarning, module=r'.*leidenalg.*')
filterwarnings(action='ignore', category=FutureWarning, message=r'functools.partial will be a method descriptor in future Python versions; wrap it in enum.member\(\) if you want to preserve the old behavior')
filterwarnings(action='ignore', category=RuntimeWarning, message=r'nopython is set for njit and is ignored')
filterwarnings(action='ignore', category=FutureWarning, message=r'Importing read_text from `anndata` is deprecated. Import anndata.io.read_text instead.')
import dask
dask.config.set({'dataframe.query-planning': True})
import dask.dataframe as dd
from squidpy.gr import (  # type: ignore
    spatial_neighbors,
    nhood_enrichment,
    co_occurrence,
    spatial_autocorr,
    # ripley,
)
from anndata import AnnData  # type: ignore
from scipy.stats import norm  # type: ignore

import numpy as np
import pandas as pd
from scanpy import logging as logg

from scipy.spatial import ConvexHull
from scipy.spatial.distance import pdist
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import LabelEncoder
from spatialdata import SpatialData

from squidpy._constants._constants import RipleyStat
from squidpy._constants._pkg_constants import Key
from squidpy._utils import NDArrayA
from squidpy.gr._utils import _assert_categorical_obs, _assert_spatial_basis, _save_data

from squidpy.gr._ripley import _reshape_res
from squidpy.gr._ripley import _f_g_function
from squidpy.gr._ripley import _l_function
from squidpy.gr._ripley import _ppp

from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.describe_features import get_feature_description
from smprofiler.db.describe_features import squidpy_feature_classnames
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

filterwarnings('ignore', message='1 variables were constant, will return nan for these.')


def ripley_custom(
    adata: AnnData | SpatialData,
    cluster_key: str,
    mode: Literal["F", "G", "L"] = "F",
    spatial_key: str = Key.obsm.spatial,
    metric: str = "euclidean",
    n_neigh: int = 2,
    n_simulations: int = 100,
    n_observations: int = 1000,
    max_dist: float | None = None,
    n_steps: int = 50,
    seed: int | None = None,
    copy: bool = False,
) -> dict[str, pd.DataFrame | NDArrayA]:
    """
    Copied from squidpy in order to alter the treatement of p values.
    https://github.com/scverse/squidpy/blob/93ee854fe4ab18583bd8bb6f1a45e9e052a0d8fa/src/squidpy/gr/_ripley.py
    """
    if isinstance(adata, SpatialData):
        adata = adata.table
    _assert_categorical_obs(adata, key=cluster_key)
    _assert_spatial_basis(adata, key=spatial_key)
    coordinates = adata.obsm[spatial_key]
    clusters = adata.obs[cluster_key].values

    mode = RipleyStat(mode)  # type: ignore[assignment]
    if TYPE_CHECKING:
        assert isinstance(mode, RipleyStat)

    # prepare support
    N = coordinates.shape[0]
    hull = ConvexHull(coordinates)
    area = hull.volume
    if max_dist is None:
        max_dist = ((area / 2) ** 0.5) / 4
    support = np.linspace(0, max_dist, n_steps)

    # prepare labels
    le = LabelEncoder().fit(clusters)
    cluster_idx = le.transform(clusters)
    obs_arr = np.empty((le.classes_.shape[0], n_steps))

    start = logg.info(
        f"Calculating Ripley's {mode} statistic for `{le.classes_.shape[0]}` clusters and `{n_simulations}` simulations"
    )

    for i in np.arange(np.max(cluster_idx) + 1):
        coord_c = coordinates[cluster_idx == i, :]
        if mode == RipleyStat.F:
            random = _ppp(hull, n_simulations=1, n_observations=n_observations, seed=seed)
            tree_c = NearestNeighbors(metric=metric, n_neighbors=n_neigh).fit(coord_c)
            distances, _ = tree_c.kneighbors(random, n_neighbors=n_neigh)
            bins, obs_stats = _f_g_function(distances.squeeze(), support)
        elif mode == RipleyStat.G:
            tree_c = NearestNeighbors(metric=metric, n_neighbors=n_neigh).fit(coord_c)
            distances, _ = tree_c.kneighbors(coordinates[cluster_idx != i, :], n_neighbors=n_neigh)
            bins, obs_stats = _f_g_function(distances.squeeze(), support)
        elif mode == RipleyStat.L:
            distances = pdist(coord_c, metric=metric)
            bins, obs_stats = _l_function(distances, support, N, area)
        else:
            raise NotImplementedError(f"Mode `{mode.s!r}` is not yet implemented.")
        obs_arr[i] = obs_stats

    sims = np.empty((n_simulations, len(bins)))
    pvalues = np.ones((le.classes_.shape[0], len(bins)))

    for i in range(n_simulations):
        random_i = _ppp(hull, n_simulations=1, n_observations=n_observations, seed=seed)
        if mode == RipleyStat.F:
            tree_i = NearestNeighbors(metric=metric, n_neighbors=n_neigh).fit(random_i)
            distances_i, _ = tree_i.kneighbors(random, n_neighbors=1)
            _, stats_i = _f_g_function(distances_i.squeeze(), support)
        elif mode == RipleyStat.G:
            tree_i = NearestNeighbors(metric=metric, n_neighbors=n_neigh).fit(random_i)
            distances_i, _ = tree_i.kneighbors(coordinates, n_neighbors=1)
            _, stats_i = _f_g_function(distances_i.squeeze(), support)
        elif mode == RipleyStat.L:
            distances_i = pdist(random_i, metric=metric)
            _, stats_i = _l_function(distances_i, support, N, area)
        else:
            raise NotImplementedError(f"Mode `{mode.s!r}` is not yet implemented.")

        for j in range(obs_arr.shape[0]):
            pvalues[j] += stats_i < obs_arr[j]
        sims[i] = stats_i

    pvalues /= n_simulations + 1
    # pvalues = np.minimum(pvalues, 1 - pvalues)

    obs_df = _reshape_res(obs_arr.T, columns=le.classes_, index=bins, var_name=cluster_key)
    sims_df = _reshape_res(sims.T, columns=np.arange(n_simulations), index=bins, var_name="simulations")

    res = {f"{mode}_stat": obs_df, "sims_stat": sims_df, "bins": bins, "pvalues": pvalues}

    if TYPE_CHECKING:
        assert isinstance(res, dict)

    if copy:
        logg.info("Finish", time=start)
        return res

    _save_data(adata, attr="uns", key=Key.uns.ripley(cluster_key, mode), data=res, time=start)
    return None


def lookup_squidpy_feature_class(method: str) -> str | None:
    for key in squidpy_feature_classnames():
        if get_feature_description(key) == method:
            return key
    return None


def compute_squidpy_metric_for_one_sample(
    df_cell: DataFrame,
    phenotypes: tuple[PhenotypeCriteria, ...],
    feature_class: str,
    radius: float | None = None,
) -> float | None:
    """Compute Squidpy metrics for a tissue sample with a clustering of the given phenotypes."""
    df_cell = df_cell.rename({
        column: (column[2:] if (column.startswith('C ') or column.startswith('P ')) else column)
        for column in df_cell.columns
    }, axis=1)
    masks: list[Series] = [
        (df_cell.astype(bool)[list(signature.positive_markers)].all(axis=1) &
         (~(df_cell.astype(bool))[list(signature.negative_markers)]).all(axis=1))
        for signature in phenotypes
    ]
    adata = convert_df_to_anndata(df_cell, masks)
    match feature_class:
        case 'neighborhood enrichment':
            if adata.obs['cluster'].nunique() == 1:
                message = 'Got 1 cluster, need 2 to compute neighborhood enrichment. Presuming null.'
                logger.error(message)
                return None
            return _summarize_neighborhood_enrichment(_nhood_enrichment(adata))
        case 'co-occurrence':
            if radius is None:
                raise ValueError('You must supply radius value for co-occurrence metric.')
            if adata.obs['cluster'].nunique() == 1:
                message = 'Got 1 cluster, need 2 to compute co-occurrence. Presuming null.'
                logger.error(message)
                return None
            return _summarize_co_occurrence(_co_occurrence(adata, radius))
        case 'ripley':
            return _summarize_ripley(_ripley(adata))
        case 'spatial autocorrelation':
            return _summarize_spatial_autocorrelation(_spatial_autocorr(adata))
    return None


def _summarize_neighborhood_enrichment(
    unstructured_metrics: dict[str, NDArray[Any]]
) -> float | None:
    if len(unstructured_metrics['zscore'].shape) != 2:
        return None
    zscore = float(unstructured_metrics['zscore'][0][1])
    return float(norm.cdf(zscore))


def _summarize_co_occurrence(unstructured_metrics: dict[str, NDArray[Any]] | None) -> float | None:
    if unstructured_metrics is None:
        return None
    occurrence_ratios = unstructured_metrics['occ']
    if len(occurrence_ratios.shape) != 3:
        return None
    return float(occurrence_ratios[0][1][0])


def _summarize_ripley(unstructured_metrics: dict[str, NDArray[Any]]) -> float | None:
    bins = unstructured_metrics['bins']
    pvalues = unstructured_metrics['pvalues']
    total_p = np_sum(pvalues)
    if len(bins) != len(pvalues) or total_p == 0:
        return None
    return round(inner(pvalues, bins) / total_p, 1)


def _summarize_spatial_autocorrelation(unstructured_metrics: DataFrame) -> float | None:
    row = unstructured_metrics.iloc[0]
    pvalue = float(row['pval_norm'])
    if isnan(pvalue):
        return None
    if pvalue == 0:
        return None
    return round10(pvalue)


def round10(value):
    return int(pow(10, 10) * value) / pow(10, 10)


def convert_df_to_anndata(
    df: DataFrame,
    phenotypes_to_cluster_on: list[Series] | None = None,
) -> AnnData:
    """Convert SMProfiler DataFrame to AnnData object for use with Squidpy metrics.

    Parameters:
        df: DataFrame
            A dataframe with an arbitrary index, x and y locations of histological structures with
            column names 'pixel x' and 'pixel y', and several columns with arbitrary names each
            indicating the expression of a phenotype.
        phenotypes_to_cluster_on: list[Series] | None
            Used to create a 'cluster' column in the AnnData object if provided. Each list is a
            mask of positive or negative features that indicate the phenotype.
            * If only one phenotype is provided, two clusters will be created mirroring the
                presence or absence of the phenotype in each histological structure.
            * If more than one is provided, the first cluster will be selected based on the
                presence of the first phenotype in each histological structure, while the second
                cluster will be selected only among histological structures that did not have the
                first phenotype, with the pattern continuing for each successive phenotype.
                Histological structures that do not have any of the phenotypes will be assigned to
                cluster 0. 
    """
    locations: NDArray[Any] = df[['pixel x', 'pixel y']].to_numpy()
    adata = AnnData(
        df.drop(['pixel x', 'pixel y'], axis=1).to_numpy(),
        obsm={'spatial': locations},  # type: ignore
    )
    spatial_neighbors(adata)
    if (phenotypes_to_cluster_on is not None) and (len(phenotypes_to_cluster_on) > 0):
        clustering = phenotypes_to_cluster_on[0].astype(int)
        i_cluster = 2
        for phenotype in phenotypes_to_cluster_on[1:]:
            clustering[(clustering == 0) & phenotype] = i_cluster
            i_cluster += 1
        adata.obs['cluster'] = clustering.to_numpy()
        adata.obs['cluster'] = adata.obs['cluster'].astype('category')
        if adata.obs['cluster'].nunique() == 1:
            logger.warning('All phenotypes provided had identical values. Only one cluster could be made.')
    return adata


def _nhood_enrichment(adata: AnnData) -> dict[str, NDArray[Any]]:
    """Compute neighborhood enrichment by permutation test."""
    result = nhood_enrichment(adata, 'cluster', copy=True, seed=128, show_progress_bar=False)
    zscore, count = cast(tuple[NDArray[Any], NDArray[Any]], result)
    return {'zscore': zscore, 'count': count}


def _co_occurrence(adata: AnnData, radius: float) -> dict[str, NDArray[Any]] | None:
    """Compute co-occurrence probability of clusters."""
    if adata.obs['cluster'].nunique() < 2:
        return None
    result = co_occurrence(
        adata,
        'cluster',
        copy=True,
        interval=[0.0, radius],  # type: ignore
        show_progress_bar=False,
    )
    occ, interval = cast(tuple[NDArray[Any], NDArray[Any]], result)
    return {'occ': occ, 'interval': interval}


def _ripley(adata: AnnData) -> dict[str, NDArray[Any]]:
    r"""Compute Ripley statistics."""
    result = ripley_custom(adata, 'cluster', copy=True, n_steps=100)
    bins = cast(NDArray[Any], result['bins'])
    pvalues = cast(NDArray[Any], result['pvalues'])
    return {
        'bins': bins,
        'pvalues': pvalues[0,],
    }


def _spatial_autocorr(adata: AnnData) -> DataFrame:
    result = spatial_autocorr(
        adata,
        attr='obs',
        genes='cluster',
        mode='moran',
        corr_method=None,
        seed=128,
        copy=True,
    )
    return result
