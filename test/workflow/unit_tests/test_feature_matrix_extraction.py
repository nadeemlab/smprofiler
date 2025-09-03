import sys

from pandas import read_csv, DataFrame

from smprofiler.db.feature_matrix_extractor import (
    FeatureMatrixExtractor,
    MatrixBundle,
)


def test_sample_set(study: dict[str, MatrixBundle]):
    if study.keys() != set(['lesion 0_1', 'lesion 6_1']):
        print(f'Wrong sample set: {list(study.keys())}')
        sys.exit(1)


def test_one_sample_set(study: dict[str, MatrixBundle]):
    if study.keys() != set(['lesion 6_1']):
        print(f'Wrong sample set: {list(study.keys())}')
        sys.exit(1)


def test_feature_matrix_schemas(study: dict[str, MatrixBundle]):
    for specimen, sample in study.items():
        df = sample.dataframe
        if df.shape != (100, 32):
            print(f'Wrong number of rows or columns: {df.shape} != (100, 32)')
            sys.exit(1)


def show_example_feature_matrix(study: dict[str, MatrixBundle]):
    specimen = 'lesion 0_1'
    df = study[specimen].dataframe
    print(f'Example feature matrix, for specimen {specimen}:')
    print(df.to_string(index=False))
    print('')


def test_channels(study: dict[str, MatrixBundle]):
    columns = list(study.values())[0].dataframe.columns
    channels = set(name[2:] for name in columns[columns.str.startswith('C ')])
    known = {'B2M', 'B7H3', 'CD14', 'CD163', 'CD20', 'CD25', 'CD27', 'CD3', 'CD4', 'CD56', 'CD68',
             'CD8', 'DAPI', 'FOXP3', 'IDO1', 'KI67', 'LAG3', 'MHCI', 'MHCII', 'MRC1', 'PD1',
             'PDL1', 'S100B', 'SOX10', 'TGM2', 'TIM3'}
    if channels != known:
        print(f'Wrong channel set: {channels}')
        sys.exit(1)


def test_expression_vectors(
    study: dict[str, MatrixBundle],
    continuous: bool = False,
    retained_structure_id: bool = False,
):
    n_cells_so_far: int = 0
    for specimen in study.keys():
        df = study[specimen].continuous_dataframe if continuous else study[specimen].dataframe

        print('Dataframe: ' + str(specimen))
        print(df)

        expression_vectors = sorted([
            tuple(row[row.index.str.startswith('C ')].tolist())
            for _, row in df.iterrows()
        ])

        filenames = {'lesion 0_1': '0.csv', 'lesion 6_1': '3.csv'}
        cells_filename = filenames[specimen]
        reference = read_csv(
            f'../test_data/adi_preprocessed_tables/dataset1/{cells_filename}', sep=',')
        if retained_structure_id:
            n_cells_added = reference.shape[0]
            reference = reference.iloc[(df.index.astype(int) - n_cells_so_far).tolist(),]
            n_cells_so_far += n_cells_added
        columns = list(study.values())[0].dataframe.columns
        channels = [name[2:] for name in columns[columns.str.startswith('C ')]]

        expected_expression_vectors = sorted([
            tuple(
                row[f'{channel}_Intensity' if continuous else f'{channel}_Positive']
                for channel in channels)
            for _, row in reference.iterrows()
        ])

        if continuous:
            def fudge_factor(vector: tuple[float, ...]):
                scale = 1.0/10.0
                return tuple(scale * v for v in vector)
            correction = list(map(fudge_factor, expected_expression_vectors))
            expected_expression_vectors = correction

        if expected_expression_vectors != expression_vectors:
            print('Expression vector sets not equal.')
            for i, expected_vector in enumerate(expected_expression_vectors):
                if expected_vector != expression_vectors[i]:
                    print(f'At sorted value {i}:')
                    print(expected_vector)
                    print(expression_vectors[i])
            sys.exit(1)
    print('Expression vector sets are as expected.')


def test_stratification(study: dict[str, DataFrame]):
    df = study['assignments']
    strata = study['strata']
    print('Sample cohorts:')
    print(df.to_string(index=False))
    print(strata.to_string(index=False))
    print('')
    if df.shape != (2, 2):
        print('Wrong number of sample cohort/stratum assignments. '
              f'Dataframe shape: {df.shape}')
        sys.exit(1)


if __name__ == '__main__':
    extractor = FeatureMatrixExtractor(database_config_file='../workflow/.smprofiler_db.config.container')
    study_name = 'Melanoma intralesional IL2 collection: abc-123'
    test_study = extractor.extract(study=study_name)
    test_sample_set(test_study)
    test_feature_matrix_schemas(test_study)
    show_example_feature_matrix(test_study)
    test_channels(test_study)
    test_expression_vectors(test_study)
    test_stratification(extractor.extract_cohorts(study_name))

    one_sample_study = extractor.extract(specimen='lesion 6_1')
    test_one_sample_set(one_sample_study)
    test_feature_matrix_schemas(one_sample_study)
    test_channels(one_sample_study)
    test_expression_vectors(one_sample_study)

    one_sample_study_continuous = extractor.extract(specimen='lesion 6_1', continuous_also=True)
    test_one_sample_set(one_sample_study_continuous)
    test_feature_matrix_schemas(one_sample_study_continuous)
    test_channels(one_sample_study_continuous)
    test_expression_vectors(one_sample_study_continuous, continuous=True)

    some_histological_structures = extractor.extract(
        study=study_name,
        histological_structures={1, 5, 7, 15, 16, 17, 150, 151, 340, 341, 2000},
        # 2000 is OOB but should skip, not fail
        retain_structure_id=True,
    )
    test_sample_set(some_histological_structures)
    show_example_feature_matrix(some_histological_structures)
    test_channels(some_histological_structures)
    test_expression_vectors(some_histological_structures, retained_structure_id=True)
