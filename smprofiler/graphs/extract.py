"""Extract graph data artifacts."""

from pandas import DataFrame, concat, merge  # type: ignore
from numpy import sort  # type: ignore

from smprofiler.db.feature_matrix_extractor import FeatureMatrixExtractor


def extract(
    database_config_file: str,
    study: str,
    strata_to_use: list[int] | None,
) -> tuple[DataFrame, DataFrame, dict[int, str]]:
    """Extract graph data artifacts.

    Parameters
    ----------
    database_config_file : str
        Location of the SMProfiler DB config file.
    study : str
        Name of the study to query data for.
    strata_to_use : list[int] | None
        Specimen strata to use as labels, identified according to the "stratum identifier" in
        `explore-classes`. This should be given as space separated integers.
        If not provided, all strata will be used.

    Returns
    -------
    df_cell: DataFrame
        Rows are individual cells, indexed by an integer ID.
        Column or column groups are, named and in order:
            1. The 'specimen' the cell is from
            2. Cell centroid positions 'pixel x' and 'pixel y'
            3. Channel expressions starting with 'C ' and followed by human-readable symbol text
            4. Phenotype expressions starting with 'P ' followed by human-readable symbol text
    df_label: DataFrame
        Rows are specimens, the sole column 'label' is its class label as an integer.
    label_to_result_text: dict[int, str]
        Mapping from class integer label to human-interpretable result text.
    """
    extractor = FeatureMatrixExtractor(database_config_file=database_config_file)
    cohorts = extractor.extract_cohorts(study)
    specimens, df_label, label_to_result_text = _create_label_df(
        cohorts['assignments'],
        cohorts['strata'],
        strata_to_use,
    )
    df_cell = _create_cell_df({
        specimen: extractor.extract(specimen=specimen, retain_structure_id=True)[specimen].dataframe
        for specimen in specimens
    } if (strata_to_use is not None) else {
        specimen: data.dataframe
        for specimen, data in extractor.extract(study=study, retain_structure_id=True).items()
    })
    return df_cell, df_label, label_to_result_text


def _create_cell_df(dfs_by_specimen: dict[str, DataFrame]) -> DataFrame:
    """Find simple and complex phenotypes, and locations and merge into a DataFrame."""
    for specimen, df_specimen in dfs_by_specimen.items():
        df_specimen['specimen'] = specimen

    df = concat(dfs_by_specimen.values(), axis=0)
    df.index.name = 'histological_structure'

    # Convert binary int columns to boolean
    channels = df.columns[df.columns.str.startswith('C ')]
    phenotypes = df.columns[df.columns.str.startswith('P ')]
    df[channels] = df[channels].astype(bool)
    df[phenotypes] = df[phenotypes].astype(bool)

    # Reorder columns so it's specimen, xy, channels, and phenotypes
    column_order = ['specimen', 'pixel x', 'pixel y']
    column_order.extend(channels)
    column_order.extend(phenotypes)
    return df[column_order]


def _create_label_df(
    df_assignments: DataFrame,
    df_strata: DataFrame,
    strata_to_use: list[int] | None,
) -> tuple[list[str], DataFrame, dict[int, str]]:
    """Get specimen-level results."""
    df_assignments['stratum identifier'] = df_assignments['stratum identifier'].astype(int)
    df_strata['stratum identifier'] = df_strata['stratum identifier'].astype(int)
    df_strata = df_strata.set_index('stratum identifier')
    df_strata = _filter_for_strata(strata_to_use, df_strata)
    df_strata = _drop_unneeded_columns(df_strata)
    df_strata = _compress_df(df_strata)
    return _label(df_assignments, df_strata)


def _filter_for_strata(strata_to_use: list[int] | None, df_strata: DataFrame) -> DataFrame:
    if strata_to_use is not None:
        df_strata = df_strata.loc[sorted(strata_to_use)]
    if df_strata.shape[0] < 2:
        raise ValueError(f'Need at least 2 strata to classify, there are {df_strata.shape[0]}.')
    return df_strata


def _drop_unneeded_columns(df_strata: DataFrame) -> DataFrame:
    """Drop columns that have internally same contents."""
    for col in df_strata.columns.tolist():
        if df_strata[col].nunique() == 1:
            df_strata = df_strata.drop(col, axis=1)
    return df_strata


def _compress_df(df_strata: DataFrame) -> DataFrame:
    """Compress remaining columns into a single string or None if all columns are empty."""
    n_columns = df_strata.shape[1]
    if n_columns == 1:
        df_strata = df_strata.rename(columns={df_strata.columns[0]: 'label'})
        df_strata.replace({'label': {'': None}}, inplace=True)
    else:
        empty_rows = (df_strata == '').all(axis=1)
        df_strata['label'] = '(' + df_strata.iloc[:, 0].astype(str)
        for i in range(1, n_columns):
            df_strata['label'] += ', ' + df_strata.iloc[:, i].astype(str)
        df_strata['label'] += ')'
        df_strata = df_strata.loc[:, ['label']]
        df_strata[empty_rows] = None
    return df_strata


def _label(
    df_assignments: DataFrame,
    df_strata: DataFrame,
) -> tuple[list[str], DataFrame, dict[int, str]]:
    """Merge with specimen assignments, keeping only selected strata."""
    df = merge(df_assignments, df_strata, on='stratum identifier', how='inner'
               ).set_index('specimen')[['label']]
    specimens: list[str] = df.index.tolist()
    df.dropna(inplace=True)
    label_to_result = dict(enumerate(sort(df['label'].unique())))
    return specimens, df.replace({res: i for i, res in label_to_result.items()}), label_to_result
