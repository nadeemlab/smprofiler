"""Strict query parameter validation."""
from typing import Annotated
from itertools import chain
import re

from fastapi import Query
from fastapi import Depends

from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.db.querying import query
from smprofiler.db.describe_features import squidpy_feature_classnames

def abbreviate_string(string: str) -> str:
    abbreviation = string[0:40]
    if len(string) > 40:
        abbreviation = abbreviation + '...'
    return abbreviation


def normalize_study_name(study: str) -> str:
    return StudyCollectionNaming.strip_token(study)[0].lower().replace(' ', '-')


async def valid_study_name(study: str = Query(min_length=3, examples=['Breast cancer IMC', 'Urothelial ICI'])) -> str:
    if study in query().retrieve_study_specifiers():
        return study
    raise ValueError(f'Study name invalid: "{abbreviate_string(study)}"')


async def valid_channel(channel: str = Query(min_length=1, examples=['CD3', 'CD8'])) -> str:
    study_names = query().retrieve_study_specifiers()
    names = list(chain(*[query().get_channel_names(study) for study in study_names]))
    names = [n.symbol for n in names]
    if channel in names:
        return channel
    raise ValueError(f'Channel name invalid: {abbreviate_string(channel)}')


def valid_composite_phenotype_name(identifier: str) -> str:
    study_names = query().retrieve_study_specifiers()
    symbols = list(chain(*[query().get_phenotype_symbols(study) for study in study_names]))
    symbols = [s.handle_string for s in symbols]
    if identifier in symbols:
        return identifier
    raise ValueError(f'Composite phenotype identifier invalid: {abbreviate_string(identifier)}')


async def valid_phenotype_symbol(phenotype_symbol: str = Query(min_length=1, examples=['1', '2'])) -> str:
    return valid_composite_phenotype_name(phenotype_symbol)


def valid_single_or_composite_identifier(identifier) -> str:
    study_names = query().retrieve_study_specifiers()
    names = list(chain(*[query().get_channel_names(study) for study in study_names]))
    names = [n.symbol for n in names]
    symbols = list(chain(*[query().get_phenotype_symbols(study) for study in study_names]))
    symbols = [s.identifier for s in symbols]
    if identifier in names:
        return identifier
    if identifier in symbols:
        return identifier
    abbreviation = abbreviate_string(identifier)
    raise ValueError(f'Channel name or phenotype identifier invalid: {abbreviation}')


async def valid_phenotype(phenotype: str = Query(min_length=1, examples=['CD3', 'CD4', '1', '2'])) -> str:
    return valid_single_or_composite_identifier(phenotype)


async def valid_phenotype_list(phenotype: list[str] = Query(min_length=1, examples=[['FOXP3', 'CD56']])) -> list[str]:
    if not all(valid_single_or_composite_identifier(p) for p in phenotype):
        raise ValueError(f'Phenotype list contains some invalid member. {phenotype}')
    return phenotype


async def valid_phenotype1(phenotype1: str = Query(min_length=1, examples=['CD3', 'CD4', '1', '2'])) -> str:
    return valid_single_or_composite_identifier(phenotype1)


async def valid_phenotype2(phenotype2: str = Query(min_length=1, examples=['CD3', 'CD4', '1', '2'])) -> str:
    return valid_single_or_composite_identifier(phenotype2)


def valid_channel_list(markers: list[str]) -> list[str]:
    study_names = query().retrieve_study_specifiers()
    names = list(chain(*[query().get_channel_names(study) for study in study_names]))
    names = [n.symbol for n in names]
    channels = names + ['']
    if all(marker in channels for marker in markers):
        return markers
    missing = [marker for marker in markers if not marker in channels]
    raise ValueError(f'Marker names invalid: {missing}')


ChannelList = Annotated[list[str], Query(examples=['B2M', 'SOX10'])]


async def valid_channel_list_positives(positive_marker: ChannelList) -> list[str]:
    return valid_channel_list(positive_marker)


async def valid_channel_list_positives2(positive_marker2: ChannelList) -> list[str]:
    return valid_channel_list(positive_marker2)


async def valid_channel_list_negatives(negative_marker: ChannelList) -> list[str]:
    return valid_channel_list(negative_marker)


async def valid_channel_list_negatives2(negative_marker2: ChannelList) -> list[str]:
    return valid_channel_list(negative_marker2)


async def valid_spatial_feature_classname(
    feature_class: str = Query(
        min_length=1,
        max_length=100,
        examples=['proximity', 'neighborhood enrichment', 'co-occurrence', 'ripley', 'spatial autocorrelation'],
    ),
) -> str:
    if feature_class not in (list(squidpy_feature_classnames()) + ['proximity']):
        raise ValueError(f'Feature class "{feature_class}" does not exist.')
    return feature_class


async def valid_spatial_feature_classname2(
    feature_class: str = Query(
        min_length=1,
        max_length=100,
        examples=['proximity', 'neighborhood enrichment', 'co-occurrence'],
    ),
) -> str:
    if feature_class not in (list(squidpy_feature_classnames()) + ['proximity']):
        raise ValueError(f'Feature class "{feature_class}" does not exist.')
    return feature_class


ValidChannel = Annotated[str, Depends(valid_channel)]
ValidStudy = Annotated[str, Depends(valid_study_name)]
ValidPhenotypeSymbol = Annotated[str, Depends(valid_phenotype_symbol)]
ValidPhenotype = Annotated[str, Depends(valid_phenotype)]
ValidPhenotypeList = Annotated[list[str], Depends(valid_phenotype_list)]
ValidChannelListPositives = Annotated[list[str], Depends(valid_channel_list_positives)]
ValidChannelListNegatives = Annotated[list[str], Depends(valid_channel_list_negatives)]
ValidChannelListPositives2 = Annotated[list[str], Depends(valid_channel_list_positives2)]
ValidChannelListNegatives2 = Annotated[list[str], Depends(valid_channel_list_negatives2)]
ValidFeatureClass = Annotated[str, Depends(valid_spatial_feature_classname)]
ValidFeatureClass2Phenotypes = Annotated[str, Depends(valid_spatial_feature_classname2)]
