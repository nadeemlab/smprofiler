"""The API service's endpoint handlers."""
from typing import cast
from typing import Annotated
from typing import Literal
from io import BytesIO
import os
from itertools import chain

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi import Header, Response, Request
from fastapi import Query
from fastapi import HTTPException
import matplotlib.pyplot as plt  # type: ignore
import jwt
from pydantic import BaseModel
from pydantic_core import from_json
from brotli import compress as brotli_compress  # type: ignore
from brotli import decompress as brotli_decompress  # type: ignore

from smprofiler.db.simple_method_cache import simple_function_cache
from smprofiler.db.exchange_data_formats.findings import finding_fields
from smprofiler.db.exchange_data_formats.findings import FindingCreate
from smprofiler.db.exchange_data_formats.findings import Finding
from smprofiler.workflow.common.umap_defaults import VIRTUAL_SAMPLE
from smprofiler.db.accessors.cells import NoContinuousIntensitiesError
from smprofiler.db.representative_subsample import SubsampleMetadata
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import DBConnection
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.apiserver.request_scheduling.ondemand_requester import OnDemandRequester
from smprofiler.db.sqlite_builder import SQLiteBuilder
from smprofiler.db.exchange_data_formats.study import StudyHandle
from smprofiler.db.exchange_data_formats.study import StudySummary
from smprofiler.db.exchange_data_formats.study import ChannelAnnotations
from smprofiler.db.exchange_data_formats.study import ChannelAliases
from smprofiler.db.exchange_data_formats.metrics import (
    PhenotypeSymbol,
    CriteriaSpecs,
    PhenotypeSymbolAndCriteria,
    Channel,
    PhenotypeCriteria,
    PhenotypeCounts,
    UnivariateMetricsComputationResult,
    AvailableGNN,
    SoftwareComponentVersion,
)
from smprofiler.db.exchange_data_formats.cells import BitMaskFeatureNames
from smprofiler.db.querying import query
from smprofiler.apiserver.app.validation import (
    normalize_study_name,
    valid_study_name,
    ValidStudy,
    ValidPhenotypeSymbol,
    ValidPhenotypeList,
    ValidChannelListPositives,
    ValidChannelListNegatives,
    ValidChannelListPositives2,
    ValidChannelListNegatives2,
    ValidFeatureClass,
    ValidFeatureClass2Phenotypes,
)
from smprofiler.apiserver.app.versions import get_software_component_versions as _get_software_component_versions
from smprofiler.apiserver.app.headers import secure_headers
from smprofiler.apiserver.app.headers import secure_headers_redoc
from smprofiler.graphs.config_reader import read_plot_importance_fractions_config
from smprofiler.graphs.importance_fractions import PlotGenerator
from smprofiler.standalone_utilities.jwk_pem import pem_from_url
from smprofiler.standalone_utilities.timestamping import now
from smprofiler.standalone_utilities.configuration_settings import get_version
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

VERSION = get_version()

TITLE = 'Single cell studies data API'

DESCRIPTION = """
# What's available

This API provides useful access to the **single-cell datasets** residing in a database that is
curated and maintained by the [Nadeem Lab](https://nadeemlab.org).

The public portion of the database includes phenotype and slide position information for:

* ~75 million cells
* across about 1500 specimens
* typically with around 30 protein targets quantified per cell
* from cancers from several sites: breast, lung, urothelial cancer and melanoma
* with a range of outcome assignments depending on the study design (often immunotherapy response)

This is the data source for the Spatial Multiomics Profiler (SMProfiler) web application located at
[smprofiler.io](https://smprofiler.io).

Using this API you can also request computation of some metrics completely on-the-fly for a given
study:

* **Phenotype fractions** per sample, with custom or pre-defined signatures
* Other per-sample metrics informed by cells' relative **spatial position**, like:
  - Proximity score between two cell populations
  - Neighborhood enrichment in a bootstrapped probabilistic sense
  - Ripley statistic summary
  - Spatial auto-correlation

Many of these metrics are computed using the [Squidpy](https://squidpy.readthedocs.io/en/stable/)
library.

You can also retrieve:

* A highly compressed **binary representation** of a given sample's **phenotype and position**
  information, suitable for live applications.
* A **UMAP** representation of a large random subsample of each study's cell set.

# Reading this documentation

This API was created using [FastAPI](https://fastapi.tiangolo.com) and
[Pydantic](https://docs.pydantic.dev/latest/).

The documentation you are reading in the browser is automatically generated and comes in two
flavors:
* the [Redoc variant](https://smprofiler.io/api/redoc)
* the [Swagger UI variant](https://smprofiler.io/api/docs)

The system of JSON-formatted return values is a simplified version of the complete
[schema](https://adiframework.com/docs_site/scstudies_quick_reference.html#) which was used to guide
the development of the SMProfiler application components.

Each endpoint (i.e. one URL for fetching a bundle of data) is documented with sample usage and a
high-level description of how to specify parameters and interpret the results. You can access these
the same way you would access any HTTP API, for example using:

* [`curl`](https://curl.se) or [`wget`](https://www.gnu.org/software/wget/) on the command line
* the [`requests`](https://requests.readthedocs.io/en/latest/) Python library
* the [Axios](https://axios-http.com/docs/intro) Javascript library
"""

app = FastAPI(
    title=TITLE,
    description=DESCRIPTION,
    version=VERSION,
    contact={
        'name': 'James Mathews',
        'url': 'https://nadeemlab.org',
        'email': 'mathewj2@mskcc.org"',
    },
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=TITLE,
        version=VERSION,
        # This is a manual replacement for 3.1.0 default, which isn't supported by Swagger UI yet.
        # openapi_version='3.0.0',
        servers=[
            {
                'url': '/api'
            }
        ],
        summary=TITLE,
        description=DESCRIPTION,
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

setattr(app, 'openapi', custom_openapi)

def is_redoc(request: Request) -> bool:
    path = request.scope['path']
    parts = list(filter(lambda t: t != '', path.split('/')))
    if len(parts) == 0:
        return False
    endpoint = parts[-1]
    return endpoint == 'redoc'

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    headers = secure_headers
    if is_redoc(request):
        headers = secure_headers_redoc
    await headers.set_headers_async(response)
    return response

@app.get("/study-names/")
async def get_study_names(
    collection: Annotated[str | None, Query(max_length=512, examples=['abcdef'])] = None
) -> list[StudyHandle]:
    """
    This is the list of studies or datasets, including only:
    * A short readable name or handle
    * An extended name intended for display, with some publication information

    The short names are used for reference as parameter values in many of the other endpoints, as
    described below.

    The collection parameter is a token providing access to private datasets, so it is not required.
    """
    specifiers = query().retrieve_study_specifiers()
    handles = [query().retrieve_study_handle(study) for study in specifiers]

    def is_public(study_handle: StudyHandle) -> bool:
        if StudyCollectionNaming.is_untagged(study_handle):
            return True
        _, tag = StudyCollectionNaming.strip_extract_token(study_handle)
        if query().is_public_collection(tag):
            return True
        return False
    if collection is None:
        handles = list(filter(is_public, map(query().retrieve_study_handle, specifiers)))
    else:
        if not StudyCollectionNaming.matches_tag_pattern(collection):
            raise HTTPException(
                status_code=404,
                detail=f'Collection "{collection}" is not a valid collection string.',
            )

        def tagged(study_handle: StudyHandle) -> bool:
            return StudyCollectionNaming.tagged_with(study_handle, collection)
        handles = list(filter(tagged, map(query().retrieve_study_handle, specifiers)))
    return handles


@app.get("/study-summary/")
async def get_study_summary(
    study: ValidStudy,
) -> StudySummary:
    """
    This summary includes metadata, or the small data, associated with a given study:

    * Authors
    * Institution where the research was carried out
    * Contact information
    * Kind of data measurements collected, typically a kind of imaging
    * Manuscript and data publication
    * Summary of the number of cells, specimens, measured channels
    * Grouping of samples/patients into cohorts, outcome assignments
    """
    return query().get_study_summary(study)


@app.get("/channels/")
async def get_channels(
    study: ValidStudy,
) -> list[Channel]:
    """The short symbolic names of the channels imaged or measured in a given study."""
    return query().get_channel_names(study)


@app.get("/phenotype-symbols/")
async def get_phenotype_symbols(
    study: ValidStudy,
) -> list[PhenotypeSymbolAndCriteria]:
    """The display names and identifiers for the "composite" phenotypes in a given study, defined
    by combination of positive and negative markers."""
    symbols: tuple[PhenotypeSymbol, ...] = query().get_phenotype_symbols(study)
    return list(
        PhenotypeSymbolAndCriteria(
            handle_string = s.handle_string,
            identifier = s.identifier,
            criteria = query().get_phenotype_criteria(study, s.handle_string),
        )
        for s in symbols
    )


@app.get("/phenotype-criteria/")
async def get_phenotype_criteria(
    study: ValidStudy,
    phenotype_symbol: ValidPhenotypeSymbol,
) -> PhenotypeCriteria:
    """Get lists of the positive markers and negative markers defining a given named phenotype,
    itself specified by identifier index, in the context of the given study.
    """
    return query().get_phenotype_criteria(study, phenotype_symbol)


@app.get("/anonymous-phenotype-counts-fast/")
async def get_anonymous_phenotype_counts_fast(
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    study: ValidStudy,
) -> PhenotypeCounts:
    """Alternative syntax for `phenotype-counts`. To be deprecated.
    """
    return _get_anonymous_phenotype_counts_fast(positive_marker, negative_marker, study)


def _get_anonymous_phenotype_counts_fast(
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    study: ValidStudy,
) -> PhenotypeCounts:
    connection = DBConnection()
    connection.__enter__()
    connection.get_connection()._set_autocommit(True)
    counts = _get_phenotype_counts(connection, positive_marker, negative_marker, study)
    connection.__exit__(None, None, None)
    return counts


@app.get("/phenotype-counts/")
async def get_phenotype_counts(
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    study: ValidStudy,
) -> PhenotypeCounts:
    """Computes the number of cells satisfying the given positive and negative criteria, in the
    context of a given study, for each sample individually. This request should generally be
    non-blocking, returning immediately with either a full or partial set of count values. A
    "pending" flag in the response indicates which scenario is the case. If pending, poll this
    endpoint until all values are available.
    """
    connection = DBConnection()
    connection.__enter__()
    counts = _get_phenotype_counts(connection, positive_marker, negative_marker, study, blocking=False)
    connection.__exit__(None, None, None)
    return counts


def _validate_all_channels(criteria_specs: CriteriaSpecs) -> None:
    studies = list(set(map(lambda s: s.study, criteria_specs.specifications)))
    for study in studies:
        all_channels = list(set(chain(*map(
            lambda s: s.criteria.positive_markers,
            filter(lambda s: s.study==study, criteria_specs.specifications)
        )))) + list(set(chain(*map(
            lambda s: s.criteria.negative_markers,
            filter(lambda s: s.study==study, criteria_specs.specifications)
        ))))
        validated, unrecognized = _validate_channels(tuple(all_channels), study)
        if not validated:
            raise UnrecognizedChannelError(unrecognized, study)


@simple_function_cache(maxsize=2000, log=True)
def _get_phenotype_counts_batch_cached(criteria_specs: CriteriaSpecs) -> list[PhenotypeCounts]:
    results = []
    try:
        _validate_all_channels(criteria_specs)
    except UnrecognizedChannelError as e:
        raise HTTPException(status_code=404, detail=e._custommessage)
    connection = DBConnection()
    connection.__enter__()
    for specification in criteria_specs.specifications:
        study = specification.study
        positive_markers = list(specification.criteria.positive_markers)
        negative_markers = list(specification.criteria.negative_markers)
        counts = _get_phenotype_counts(connection, positive_markers, negative_markers, study, blocking=False, validate_channels=False)
        results.append(counts)
    connection.__exit__(None, None, None)
    return results


@app.post("/phenotype-counts-batch/")
async def get_phenotype_counts_batch(criteria_specs: CriteriaSpecs) -> list[PhenotypeCounts]:
    results = _get_phenotype_counts_batch_cached(criteria_specs)
    return results


@app.get("/request-spatial-metrics-computation/")
async def request_spatial_metrics_computation(
    study: ValidStudy,
    phenotype: ValidPhenotypeList,
    feature_class: ValidFeatureClass2Phenotypes,
    radius: float | None = None,
) -> UnivariateMetricsComputationResult:
    """Spatial proximity statistics like the single-phenotype case, but between *two* phenotype cell
    sets, where the phenotypes are specified by index among the pre-defined/combination phenotypes
    for the given study."""
    phenotypes = phenotype
    criteria: list[PhenotypeCriteria] = [
        query().retrieve_signature_of_phenotype(p, study) for p in phenotypes
    ]
    markers: list[list[str]] = []
    for criterion in criteria:
        markers.append(list(criterion.positive_markers))
        markers.append(list(criterion.negative_markers))
    connection = DBConnection()
    connection.__enter__()
    metrics = get_squidpy_metrics(connection, study, markers, feature_class, radius=radius)
    connection.__exit__(None, None, None)
    return metrics


@app.get("/request-spatial-metrics-computation-custom-phenotype/")
async def request_spatial_metrics_computation_custom_phenotype(
    study: ValidStudy,
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    feature_class: ValidFeatureClass,
    radius: float | None = None,
) -> UnivariateMetricsComputationResult:
    """Spatial proximity statistics for a single custom-defined phenotype (cell set). Different
    metrics are available, including several provided by the Squidpy package. If a feature class is
    specified which requires two cell sets, the provided cell set will be duplicated. The radius
    value provides a scale to the metric computation algorithm. Here "request" connotes that the
    query will request computation and then return. Poll this endpoint until all values are
    available. Note that `positive_marker` and `negative_marker` paramters can be supplied
    multiple times, once for each item in the list of positive or negative markers respectively.
    """
    markers = [positive_marker, negative_marker]
    connection = DBConnection()
    connection.__enter__()
    metrics = get_squidpy_metrics(connection, study, markers, feature_class, radius=radius)
    connection.__exit__(None, None, None)
    return metrics

@app.get("/request-spatial-metrics-computation-custom-phenotypes/")
async def request_spatial_metrics_computation_custom_phenotypes(  # pylint: disable=too-many-arguments
    study: ValidStudy,
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    positive_marker2: ValidChannelListPositives2,
    negative_marker2: ValidChannelListNegatives2,
    feature_class: ValidFeatureClass,
    radius: float | None = None,
) -> UnivariateMetricsComputationResult:
    """Spatial proximity statistics for a pair of custom-defined phenotypes (cell sets).
    """
    markers = (positive_marker, negative_marker, positive_marker2, negative_marker2)
    connection = DBConnection()
    connection.__enter__()
    if feature_class == 'proximity':
        if radius is None:
            radius = 30.0
        metrics = get_proximity_metrics(connection, study, markers, radius=radius)
    metrics =  get_squidpy_metrics(connection, study, list(markers), feature_class, radius=radius)
    connection.__exit__(None, None, None)
    return metrics

class SpatialMetricsRequest(BaseModel):
    study: ValidStudy
    positive_marker: ValidChannelListPositives
    negative_marker: ValidChannelListNegatives
    positive_marker2: ValidChannelListPositives2
    negative_marker2: ValidChannelListNegatives2
    feature_class: ValidFeatureClass
    radius: float | None = None


class BatchSpatialMetricsRequest(BaseModel):
    """
    Specification for multiple spatial metrics computation requests.
    """
    specifications: list[SpatialMetricsRequest]


@app.post("/batch-request-spatial-metrics-computation-custom-phenotypes/")
async def batch_request_spatial_metrics_computation_custom_phenotypes(
    batch: BatchSpatialMetricsRequest
) -> list[UnivariateMetricsComputationResult]:
    """
    Spatial proximity statistics for a pair of custom-defined phenotypes (cell sets).
    """
    results = []
    connection = DBConnection()
    connection.__enter__()
    for i, specification in enumerate(batch.specifications):
        s = specification
        markers = (s.positive_marker, s.negative_marker, s.positive_marker2, s.negative_marker2)
        if s.feature_class == 'proximity':
            if s.radius is None:
                radius = 30.0
            else:
                radius = s.radius
            results.append(get_proximity_metrics(connection, s.study, markers, radius=radius))
        else:
            results.append(get_squidpy_metrics(connection, s.study, list(markers), s.feature_class, radius=s.radius))
        if i % 50 == 0:
            logger.debug(f'Completed {i+1}/{len(batch.specifications)} requests out of batch.')
    connection.__exit__(None, None, None)
    return results


@app.get("/available-gnn-metrics/")
async def available_gnn_metrics(
    study: ValidStudy,
) -> AvailableGNN:
    return query().get_available_gnn(study)


@app.get("/importance-composition/")
async def get_importance_composition(
    study: ValidStudy,
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    plugin: str = 'cg-gnn',
    datetime_of_run: str = 'latest',
    plugin_version: str | None = None,
    cohort_stratifier: str | None = None,
    cell_limit: int = 100,
) -> PhenotypeCounts:
    """For each specimen, return the fraction of important cells expressing a given phenotype."""
    return _get_importance_composition(
        study,
        positive_marker,
        negative_marker,
        plugin,
        datetime_of_run,
        plugin_version,
        cohort_stratifier,
        cell_limit,
    )

def _get_importance_composition(
    study: ValidStudy,
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    plugin: str = 'cg-gnn',
    datetime_of_run: str = 'latest',
    plugin_version: str | None = None,
    cohort_stratifier: str | None = None,
    cell_limit: int = 100,
) -> PhenotypeCounts:
    """For each specimen, return the fraction of important cells expressing a given phenotype."""
    cells_selected = query().get_important_cells(
        study,
        plugin,
        datetime_of_run,
        plugin_version,
        cohort_stratifier,
        cell_limit,
    )
    connection = DBConnection()
    connection.__enter__()
    counts = _get_phenotype_counts(
        connection,
        positive_marker,
        negative_marker,
        study,
        cells_selected,
    )
    connection.__exit__(None, None, None)
    return counts

def _get_phenotype_counts_cached(
    connection: DBConnection,
    positives: tuple[str, ...],
    negatives: tuple[str, ...],
    study: str,
    selected: tuple[int, ...],
    blocking: bool,
) -> PhenotypeCounts:
    counts = OnDemandRequester.get_counts_by_specimen(
        connection,
        positives,
        negatives,
        study,
        set(selected) if selected is not None else None,
        blocking = blocking,
    )
    return counts


class UnrecognizedChannelError(ValueError):
    def __init__(self, unrecognized: list[str], study: str):
        self._unrecognized = unrecognized
        self._study = study
        self._custommessage = f'In "{study}", channels not recognized: {unrecognized}'
        super().__init__(self._custommessage)


def _validate_channels(channel_names: tuple[str, ...], study: str) -> tuple[bool, list[str]]:
    symbols = cast(tuple[Channel, ...], query().get_channel_names(study))
    names = tuple(map(lambda s: s.symbol, symbols))
    unrecognized = set(list(channel_names)).difference(set(names))
    if len(unrecognized) > 0:
        return (False, list(unrecognized))
    return (True, [])


def _get_phenotype_counts(
    connection: DBConnection,
    positive_marker: ValidChannelListPositives,
    negative_marker: ValidChannelListNegatives,
    study: ValidStudy,
    cells_selected: set[int] | None = None,
    blocking: bool = True,
    validate_channels: bool = True,
) -> PhenotypeCounts:
    """For each specimen, return the fraction of selected/all cells expressing the phenotype."""
    positive_markers = [m for m in positive_marker if m != '']
    negative_markers = [m for m in negative_marker if m != '']
    if validate_channels:
        validated, unrecognized = _validate_channels(tuple(positive_markers + negative_markers), study)
        if not validated:
            raise UnrecognizedChannelError(unrecognized, study)
    counts = _get_phenotype_counts_cached(
        connection,
        tuple(positive_markers),
        tuple(negative_markers),
        study,
        tuple(sorted(list(cells_selected))) if cells_selected is not None else (),
        blocking,
    )
    return counts


def get_proximity_metrics(
    connection: DBConnection,
    study: str,
    markers: tuple[list[str], list[str], list[str], list[str]],
    radius: float,
) -> UnivariateMetricsComputationResult:
    return OnDemandRequester.get_proximity_metrics(
        connection,
        study,
        radius,
        markers,
    )


def get_squidpy_metrics(
    connection: DBConnection,
    study: str,
    markers: list[list[str]],
    feature_class: str,
    radius: float | None = None,
) -> UnivariateMetricsComputationResult:
    return OnDemandRequester.get_squidpy_metrics(
        connection,
        study,
        markers,
        feature_class,
        radius=radius,
    )


@app.get("/cell-data-binary/")
async def get_cell_data_binary(
    study: ValidStudy,
    sample: Annotated[str, Query(max_length=512)],
    accept_encoding: Annotated[str, Header()] = '',
):
    """
    Get cell-level location and phenotype data in a custom binary format.
    The format is documented [here](https://github.com/nadeemlab/SMProfiler/blob/main/docs/cells.md).

    The sample may be "UMAP virtual sample" if UMAP dimensional reduction is available.
    """

    _accept_encoding = tuple(enc.strip() for enc in accept_encoding.split(','))

    has_umap = query().has_umap(study)
    if not sample in query().get_sample_names(study) and not (has_umap and sample == VIRTUAL_SAMPLE):
        raise HTTPException(status_code=404, detail=f'Sample "{sample}" does not exist.')

    data, content_encoding = query().get_cells_data(study, sample, accept_encoding=_accept_encoding)

    return Response(
        data,
        headers={"Content-Encoding": content_encoding} if content_encoding else {},
    )


@app.get("/cell-data-binary-feature-names/")
async def get_cell_data_binary_feature_names(study: ValidStudy) -> BitMaskFeatureNames:
    """
    Get the features corresponding to the channels in the binary/bitmask representation of a cell's
    channel positivity/negativity assignments.
    """
    return query().get_ordered_feature_names(study)


@app.get("/cell-data-binary-intensity/")
async def get_cell_data_binary_intensity(
    study: ValidStudy,
    sample: Annotated[str, Query(max_length=512)],
    accept_encoding: Annotated[str, Header()] = '',
):
    """
    Get cell-level intensity data for each cell and channel. The channel order is the same as in
    `cell-data-binary`, but note that in the binary format here, 1 byte is used for each channel's
    value, so the number of bytes in each "row" (for a single cell) is variable depending on the
    number of channels (unlike the bit-wise binary format for the discrete 0/1 values).

    The cell order (order of "rows") is the same as in `cell-data-binary`.

    The sample may be "UMAP virtual sample" if UMAP dimensional reduction is available.
    """
    has_umap = query().has_umap(study)
    if not sample in query().get_sample_names(study) and not (has_umap and sample == VIRTUAL_SAMPLE):
        raise HTTPException(status_code=404, detail=f'Sample "{sample}" does not exist.')

    if not 'br' in accept_encoding:
        raise HTTPException(status_code=400, detail='Only brotli encoding supported.')

    data = query().get_cells_data_intensity(study, sample, accept_encoding=('br',))
    return Response(
        data,
        headers={"Content-Encoding": 'br'},
    )


@app.get("/cell-data-binary-intensity-whole-study-subsample/")
async def get_cell_data_binary_intensity_whole_study_subsample(
    study: ValidStudy,
    accept_encoding: Annotated[str, Header()] = 'br',
):
    """
    Get cell-level marker intensity data for a subsample of all cells in the given study, in a
    custom binary format. The format is documented [here](https://github.com/nadeemlab/SMProfiler/blob/main/docs/cells.md).
    """
    if not 'br' in accept_encoding:
        raise HTTPException(status_code=400, detail=f'Only brotli encoding supported. Got: "{accept_encoding}"')
    try:
        data = query().get_cells_data_intensity_whole_study_subsample(study, accept_encoding=('br',))
    except NoContinuousIntensitiesError as error:
        logger.error(error.message)
        raise HTTPException(status_code=404, detail=f'Continuous intensity data not available for this study.')
    return Response(
        data,
        headers={"Content-Encoding": 'br'},
    )


@app.get("/whole-study-subsample-binary/")
async def get_whole_study_subsample_binary(
    study: ValidStudy,
    accept_encoding: Annotated[str, Header()] = 'br',
):
    """
    Convenience accessor for binary portion of cell-data-binary-intensity-whole-study-subsample response.
    """
    if not 'br' in accept_encoding:
        raise HTTPException(status_code=400, detail=f'Only brotli encoding supported. Got: "{accept_encoding}"')
    try:
        data = query().get_cells_data_intensity_whole_study_subsample_binary_only(study, accept_encoding=('br',))
    except NoContinuousIntensitiesError as error:
        logger.error(error.message)
        raise HTTPException(status_code=404, detail=f'Continuous intensity data not available for this study.')
    return Response(
        data,
        headers={"Content-Encoding": 'br'},
    )


@app.get("/whole-study-subsample-metadata/")
async def get_whole_study_subsample_metadata(
    study: ValidStudy,
) -> SubsampleMetadata:
    """
    Convenience accessor for metadata portion of cell-data-binary-intensity-whole-study-subsample response.
    """
    try:
        data = brotli_decompress(query().get_cells_data_intensity_whole_study_subsample(study, accept_encoding=('br',)))
    except NoContinuousIntensitiesError as error:
        logger.error(error.message)
        raise HTTPException(status_code=404, detail=f'Continuous intensity data not available for this study.')
    offset = cast(int, locate_offset(data))
    metadata_json = data[0:offset].decode('utf-8')
    return SubsampleMetadata.model_validate(from_json(metadata_json))


def locate_offset(raw: bytes) -> int | None:
    file_separator = int.to_bytes(28)
    for i in range(len(raw)):
        if raw[i:i+1] == file_separator:
            return i
    return None


@app.get("/software-component-versions/")
async def get_software_component_versions() -> list[SoftwareComponentVersion]:
    """
    Get the versions of software dependencies, to help pin specific computation results.
    """
    return _get_software_component_versions()


def _ensure_plot_cache_exists(study: str):
    with DBCursor(study=study) as cursor:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS gnn_plot_cache(
            img_format VARCHAR(3),
            blob_contents bytea
        ) ;
        ''')


def _retrieve_gnn_plot(study: str, img_format: str) -> bytes | None:
    with DBCursor(study=study) as cursor:
        cursor.execute('''
        SELECT blob_contents
        FROM gnn_plot_cache
        WHERE img_format=%s
        ''', (img_format,))
        rows = tuple(cursor.fetchall())
    if len(rows) == 0:
        return None
    return bytes(rows[0][0])


def _write_gnn_plot(contents: bytes, study: str, img_format: str) -> None:
    with DBCursor(study=study) as cursor:
        cursor.execute('''
        INSERT INTO gnn_plot_cache(img_format, blob_contents)
        VALUES (%s, %s) ;
        ''', (img_format, contents))


def get_importance_fraction_plot(study: str, img_format: str) -> bytes:
    _ensure_plot_cache_exists(study)
    contents = _retrieve_gnn_plot(study, img_format)
    if contents is not None:
        return contents

    settings: str = cast(list[str], query().get_study_gnn_plot_configurations(study))[0]
    (
        _,
        _,
        phenotypes,
        cohorts,
        plugins,
        figure_size,
        orientation,
    ) = read_plot_importance_fractions_config(None, settings, True)

    generator = PlotGenerator(
        (
            _get_anonymous_phenotype_counts_fast,
            query().get_study_summary,
            query().get_phenotype_criteria,
            _get_importance_composition,
        ),  # type: ignore
        study,
        phenotypes,
        cohorts,
        plugins,
        figure_size,
        orientation,
    )
    plot = generator.generate_plot()
    plt.figure(plot.number)  # type: ignore
    buffer = BytesIO()
    plt.savefig(buffer, format=img_format)
    buffer.seek(0)
    contents = buffer.read()
    _write_gnn_plot(contents, study, img_format)
    return contents


@app.get("/importance-fraction-plot/")
async def importance_fraction_plot(
    study: ValidStudy,
    img_format: Literal['svg', 'png'] = 'svg',
) -> Response:
    """Return a plot of the fraction of the top most important cells for GNN classification,
    expressing various phenotypes."""
    raw = get_importance_fraction_plot(str(study), str(img_format))
    media_type = "image/svg+xml" if img_format == "svg" else "image/png"
    return Response(raw, media_type=media_type)


@app.post("/findings/")
async def create_finding(finding: FindingCreate) -> Finding:
    if os.environ['ORCID_ENVIRONMENT'] == 'sandbox':
        issuer = 'https://sandbox.orcid.org'
    elif os.environ['ORCID_ENVIRONMENT'] == 'production':
        issuer = 'https://orcid.org'
    orcid_cert = pem_from_url(f'{issuer}/oauth/jwks')
    if os.environ['ORCID_ENVIRONMENT'] == 'sandbox' and os.environ['SMProfiler_TESTING_MODE'] == '1':
        data = {'sub': '0000', 'given_name': 'First', 'family_name': 'Last'}
        status = 'published'
    else:
        data = jwt.decode(
            finding.id_token,
            key=orcid_cert,
            algorithms=['RS256'],
            audience=os.environ['ORCID_CLIENT_ID'],
            issuer=[issuer]
        )
        status = 'pending_review'
    new_finding = (
        finding.study,
        now(),
        None,
        status,
        data['sub'],
        data['given_name'],
        data.get('family_name', ''),
        finding.email,
        finding.url,
        finding.description,
        finding.background,
        finding.p_value,
        finding.effect_size
    )
    try:
        study = await valid_study_name(finding.study)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f'"{finding.study}" is not a valid study.',
        )
    with DBCursor() as cursor:
        cursor.execute(
            'INSERT INTO finding VALUES (DEFAULT,%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);',
            new_finding,
        )
    return Finding(id=-1, **{key: new_finding[i] for i, key in enumerate(finding_fields)})  # type: ignore


@app.get("/findings/")
def get_findings(
    study: ValidStudy,
    limit: Annotated[int, Query(le=100)] = 100,
) -> list[Finding]:
    with DBCursor() as cursor:
        cursor.execute(
            'SELECT * FROM finding f WHERE f.study=%s AND f.status=%s LIMIT %s ;',
            (study, 'published', limit),
        )
        rows = tuple(cursor.fetchall())
    return list(map(lambda row: Finding(id=-1, **{key: row[i + 1] for i, key in enumerate(finding_fields)}), rows))


@app.get("/channel-annotations/")
async def get_channel_annotations() -> ChannelAnnotations:
    """
    Get the presentation-layer annotations (groupings, colors, etc.) for all channels.
    """
    return query().get_channel_annotations()


@app.get("/channel-aliases/")
async def get_channel_aliases() -> ChannelAliases:
    """
    Get the presentation-layer shorthand/abbreviations/aliases for all channels.
    """
    return query().get_channel_aliases()


@app.get("/sqlite/")
def get_sqlite_dump(
    study: ValidStudy,
    no_feature_values: str | None = None,
    no_feature_specifications: str | None = None,
):
    """
    Get a SQLite database dump of all the metadata for a study.
    By default, this includes all computed features.
    To omit the computed feature values, include query parameter `no_feature_values`.
    To omit even the feature specifications/definitions, include query parameter `no_feature_specifications`.
    """
    connection = DBConnection()
    connection.__enter__()
    builder = SQLiteBuilder(
        connection,
        no_feature_values=no_feature_values is not None,
        no_feature_specifications=no_feature_specifications is not None,
    )
    sqlite_db = builder.get_dump(study)
    connection.__exit__(None, None, None)
    return Response(
        sqlite_db,
        headers={
            "Content-Type": 'application/vnd.sqlite3',
            "Content-Disposition": f'attachment; filename="{normalize_study_name(study)}.sqlite"'
        },
    )
