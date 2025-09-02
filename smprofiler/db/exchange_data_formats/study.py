"""Data structures for ready exchange, related to an overall study."""

from pydantic import BaseModel


class StudyComponents(BaseModel):
    """Main substudies of a primary study."""
    collection: str
    measurement: str
    analysis: str


class StudyHandle(BaseModel):
    """A study specifier (or handle), together with an extended for-display variant."""
    handle: str
    display_name_detail: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "handle": "Dataset ABC",
                    "display_name_detail": "Dataset ABC - Nature 2030"
                }
            ]
        }
    }


class Institution(BaseModel):
    """
    The institution, for example a research organization, in which a study took place or in which
    the study was carried out.
    """
    name: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "University of Zurich"
                },
            ]
        }
    }


class Assay(BaseModel):
    """
    This is a minimal tag indicating the method of assessment or measurement of feature data. This
    may sometimes be called data "modality".
    """
    name: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Imaging mass cytometry"
                },
            ]
        }
    }


class StudyContact(BaseModel):
    """
    This is contact information for a person who is at least semi-formally responsible for fielding
    inquiries regarding the study and/or its data products, due to being listed as a lead author
    or research group leader or similar.
    """
    name: str
    email_address: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Hartland W. Jackson",
                    "email_address": "hjackson@lunenfeld.ca"
                },
            ]
        }
    }


class DataRelease(BaseModel):
    """
    This is basic information about a published/released dataset, sufficient for an application to
    provide a reasonable reference that a user could follow up on via the URL for more detail.
    """
    repository: str
    url: str
    date: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "repository": "Zenodo (CERN)",
                    "url": "https://doi.org/10.5281/zenodo.4607374",
                    "date": "2019-11-04",
                },
            ]
        }
    }


class Publication(BaseModel):
    """
    This is basic information about a published article, sufficient for an application to provide
    a reasonable reference that a user could follow via the URL for more detail. So the longevity
    of the reference function is dependent on that of the URL.
    """
    title: str
    url: str
    first_author_name: str
    date: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "The single-cell pathology landscape of breast cancer",
                    "url": "https://doi.org/10.1038/s41586-019-1876-x",
                    "first_author_name": "Hartland W. Jackson",
                    "date": "2020-01-20",
                }
            ]
        }
    }


class CountsSummary(BaseModel):
    """
    This is a summary including the number of samples, cells, channels, and pre-defined combinations
    ("composite phenotypes"). This is provided for convenience, without requiring review of the
    per-sample values.
    """
    specimens: int
    cells: int
    channels: int
    composite_phenotypes: int
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "specimens": 169,
                    "cells": 430029,
                    "channels": 33,
                    "composite_phenotypes": 3,
                },
            ]
        }
    }


class Cohort(BaseModel):
    """
    This is a cohort or stratum in the primary stratification for a study, if available.
    Often a cohort may be defined by a *diagnosis* event and diagnosis *result*, sometimes with a
    *temporality* indicating something about when the event took place.

    The *identifier* field is used for reference.
    """
    identifier: str
    temporality: str
    diagnosis: str
    result: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "identifier": "1",
                    "temporality": "Before intervention",
                    "diagnosis": "Response to hormone therapy",
                    "result": "Refractory"
                },
                {
                    "identifier": "2",
                    "temporality": "Before intervention",
                    "diagnosis": "Response to hormone therapy",
                    "result": "Sensitive"
                },
                {
                    "identifier": "3",
                    "temporality": "Before intervention",
                    "diagnosis": "Response to hormone therapy",
                    "result": "Resistant"
                },
            ]
        }
    }


class CohortAssignment(BaseModel):
    """This is one assignment of a sample to a cohort."""
    sample: str
    cohort: str
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "sample": "BaselTMA_SP41_101_X10Y8",
                    "cohort": "1"
                },
                {
                    "sample": "BaselTMA_SP43_95_X13Y2",
                    "cohort": "3"
                },
            ]
        }
    }


class SampleCohorts(BaseModel):
    """
    This is the primary cohort stratification for a study, if one is available, often used to state
    the primary findings.
    """
    assignments: list[CohortAssignment]
    cohorts: list[Cohort]


class Context(BaseModel):
    """These are a few annotations of the context or manner in which a study was performed."""
    institution: Institution
    assay: Assay
    contact: StudyContact


class Products(BaseModel):
    """These are the formal research products of a given study."""
    data_release: DataRelease
    publication: Publication


class StudySummary(BaseModel):
    """This is a convenience aggregation of summary and metadata for a given study."""
    context: Context
    products: Products
    counts: CountsSummary
    cohorts: SampleCohorts
    findings: list[str]
    has_umap: bool
    has_intensities: bool
    curation_notes: str | None


class ChannelGroupAnnotation(BaseModel):
    channels: list[str]
    color: str


class ChannelAnnotations(BaseModel):
  channelGroups: dict[str, ChannelGroupAnnotation]


class ChannelAliases(BaseModel):
  aliases: dict[str, str]
