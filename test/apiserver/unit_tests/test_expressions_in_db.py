"""Basic testing that expression vectors are in the database."""
import re
from typing import cast

from pandas import DataFrame
from pandas import read_csv
from numpy import sqrt

from smprofiler.db.feature_matrix_extractor import FeatureMatrixExtractor

def _compare(original: DataFrame, retrieved: DataFrame) -> None:
    _check_locations(original, retrieved)
    _check_discrete_vectors(original, retrieved)

def _check_locations(original: DataFrame, retrieved: DataFrame) -> None:
    for (_, row1), (_, row2) in zip(original.iterrows(), retrieved.iterrows()):
        assert row1['XMin'] <= row2['pixel x']
        assert row1['XMax'] >= row2['pixel x']
        assert row1['YMin'] <= row2['pixel y']
        assert row1['YMax'] >= row2['pixel y']

def _map_channel(df: DataFrame, column_indicator: str='_Positive') -> dict[str, str]:
    return {c: 'C ' + re.sub(column_indicator, '', c)
        for c in df.columns if re.search(column_indicator, c)
    }

def _check_discrete_vectors(original: DataFrame, retrieved: DataFrame) -> None:
    map_channel = _map_channel(original)
    for i, ((_, row1), (_, row2)) in enumerate(zip(original.iterrows(), retrieved.iterrows())):
        for c1, c2 in map_channel.items():
            if row1[c1] != row2[c2]:
                raise ValueError(f'Cell {i} mismatch: {c1}, {c2}: ({row1[c1]}, {row2[c2]})')

def _check_intensities(original: DataFrame, retrieved: DataFrame) -> None:
    map_channel = _map_channel(original, column_indicator='_Intensity')
    factors = []
    for c1, c2 in map_channel.items():
        print(f'Checking intensity channels for concordance: {(c1, c2)} ... ', end='')
        for (_, row1), (_, row2) in zip(original.iterrows(), retrieved.iterrows()):
            v1 = float(row1[c1])
            v2 = float(row2[c2])
            if v2 != 0:
                factor = v1 / v2
            else:
                factor = '--'
            if factor != '--' and v2 < 1.0 and v2 > 0:
                factors.append(factor)
        m = sum(factors) / len(factors)
        std = float(sqrt(sum(pow(f-m, 2) for f in factors))) / len(factors)
        assert(m > 9.5 and m < 10.5)
        assert(std < 0.25)
        print('Done.')

def test_one_expressions_matrix():
    database_config_file = '.smprofiler_db.config.container'
    study = 'Melanoma intralesional IL2'
    specimen = 'lesion 0_1'
    bundle = FeatureMatrixExtractor(database_config_file).extract(specimen, study, continuous_also=True)
    original = read_csv('../test_data/adi_preprocessed_tables/dataset1/0.csv')
    _compare(original, bundle['lesion 0_1'].dataframe)
    print('Locations in 0.csv match cell locations in processed feature matrix for lesion 0_1.')
    print('Discrete vectors in 0.csv match cell phenotype vectors in processed feature matrix for lesion 0_1.')
    _check_intensities(original, cast(DataFrame, bundle['lesion 0_1'].continuous_dataframe))

if __name__=='__main__':
    test_one_expressions_matrix()
