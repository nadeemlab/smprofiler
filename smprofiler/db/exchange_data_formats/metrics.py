"""Data structures for ready exchange, related to computations or derived metrics."""

from pydantic import BaseModel  # pylint: disable=no-name-in-module

from smprofiler.graphs.plugin_constants import GNNPlugin


class FeatureAssociationTest(BaseModel):
    """One test for association between two cohorts along a feature."""
    feature: str
    cohort1: str
    cohort2: str
    pvalue: float


class PhenotypeSymbol(BaseModel):
    """The display/handle string and the internal identifier for a phenotype."""
    handle_string: str
    identifier: str


class Channel(BaseModel):
    """The symbol for one of the imaged or measured channels."""
    symbol: str
    full_name: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {'symbol': 'CD3'},
                {'symbol': 'CD4'},
                {'symbol': 'FOXP3'},
            ]
        }
    }


class PhenotypeCriteria(BaseModel, frozen=True):
    """Criteria defining a "composite" phenotype by expression and non-expression of markers."""
    positive_markers: tuple[str, ...]
    negative_markers: tuple[str, ...]
    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'positive_markers': ['CD3', 'CD4'],
                    'negative_markers': ['FOXP3'],
                },
                {
                    'positive_markers': ['SOX10'],
                    'negative_markers': [],
                },
            ]
        }
    }


class StudySpecificPhenotypeCriteria(BaseModel, frozen=True):
    criteria: PhenotypeCriteria
    study: str


class CriteriaSpecs(BaseModel, frozen=True):
    """Like PhenotypeCriteria, but several, to specify batch operations."""
    specifications: tuple[StudySpecificPhenotypeCriteria, ...]


class PhenotypeSymbolAndCriteria(BaseModel):
    """The display/handle string and the internal identifier for a phenotype."""
    handle_string: str
    identifier: str
    criteria: PhenotypeCriteria
    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'handle_string': 'T regulatory cells',
                    'identifier': '8',
                    'criteria': {
                        'positive_markers': ['CD3', 'CD4', 'FOXP3'],
                        'negative_markers': [],
                    }
                },
            ]
        }
    }


class WrapperPhenotype(BaseModel):
    """The phenotype criteria used during the counting procedure (not applicable in GNN case).
    """
    criteria: PhenotypeCriteria
    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'criteria': {
                        'positive_markers': ['CD3', 'CD4', 'FOXP3'],
                        'negative_markers': [],
                    },
                },
            ]
        }
    }


class PhenotypeCount(BaseModel):
    """The number of cells (and formatted/rounded percentage or fraction) in a given specimen,
    belonging to some specific class.
    """
    specimen: str
    count: int | None
    percentage: float | None
    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'specimen': 'Sample001',
                    'count': 3108,
                    'percentage': 42.3,
                },
            ]
        }
    }


class PhenotypeCounts(BaseModel):
    """The number of cells of a given phenotype across all samples in a given study."""
    counts: tuple[PhenotypeCount, ...]
    phenotype: WrapperPhenotype
    is_pending: bool


class UnivariateMetricsComputationResult(BaseModel):
    """The response to a request for retrieval of derived/computed metrics (typically a spatially-
    enrich feature), or a request for such metrics to be computed as a background job.
    """
    values: dict[str, float | None]
    is_pending: bool
    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'values': {
                        'Sample001': 3.4,
                        'Sample700': 0.01,
                        'Sample715': 0.02,
                    },
                    'is_pending': False,
                },
            ]
        }
    }


class CellData(BaseModel):
    """Cell-level data including position and phenotype information, for a single sample.
    """
    feature_names: list[str]
    cells: list[list[str | float | int]]


class AvailableGNN(BaseModel):
    """List of available GNN metrics, i.e. which plugins were used in a completed run."""
    plugins: tuple[GNNPlugin, ...]


class SoftwareComponentVersion(BaseModel):
    """
    Version metadata for a software component. The format is the form of the component, whether a
    package, framework, docker or container image, etc. The source is the repository from which the
    component was downloaded. The flag relevant_to_reproducible_computation is intended to indicate
    components that are expected to have an effect on exact computed values (rather than, for
    example, just affecting performance or data formats).
    """
    component_name: str
    format: str
    source: str
    version: str
    relevant_to_reproducible_computation: bool
    model_config = {
        'json_schema_extra': {
            'examples': [
                {
                    'component_name': 'Squidpy',
                    'format': 'Python package',
                    'source': 'Python package index (PyPI)',
                    'relevant_to_reproducible_computation': True,
                    'version': '1.5.0',
                },
            ]
        }
    }
