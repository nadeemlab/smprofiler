"""Convenience provision of a feature matrix for each study, retrieved from the SMProfiler database."""

from typing import cast, Any
from dataclasses import dataclass

from pandas import DataFrame

from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import retrieve_study_from_specimen
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.accessors.phenotypes import PhenotypesAccess
from smprofiler.db.stratification_puller import (
    StratificationPuller,
    Stratification,
)
from smprofiler.workflow.common.structure_centroids import StudyStructureCentroids
from smprofiler.workflow.common.structure_centroids_puller import \
    StructureCentroidsPuller
from smprofiler.workflow.common.sparse_matrix_puller import (
    SparseMatrixPuller,
    StudyDataArrays,
)
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


@dataclass
class MatrixBundle:
    """Bundle of information for a specimen matrix."""
    dataframe: DataFrame
    filename: str
    continuous_dataframe: DataFrame | None = None


class FeatureMatrixExtractor:
    """Pull from the database and create convenience bundle of feature matrices and metadata."""
    database_config_file: str | None

    def __init__(self, database_config_file: str | None) -> None:
        self.database_config_file = database_config_file

    def extract(self,
        specimen: str | None = None,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
        retain_structure_id: bool = False,
    ) -> dict[str, MatrixBundle]:
        """Extract feature matrices for a specimen or every specimen in a study.

        Parameters
        ----------
        specimen: str | None = None
        study: str | None = None
            Which specimen to extract features for or study to extract features for all specimens
            for. Exactly one of specimen or study must be provided.
        histological_structures: set[int] | None = None
            Which histological structures to extract features for from the given study or specimen,
            by their histological structure ID. Structures not found in either the provided
            specimen or study are ignored.
            If None, all structures are fetched.
        continuous_also: bool = False
            Whether to also calculate and return a DataFrame for each specimen with continuous
            channel information in addition to the default DataFrame which provides binary cast
            channel information.
        retain_structure_id: bool = False
            Whether to index cells by their histological structure ID rather than arbitrary indices.

        Returns
        -------
        dict[str, MatrixBundle]
            A dictionary of specimen names to a MatrixBundle dataclass instances, which contain:
                1. `dataframe`, a DataFrame with the feature matrix for the specimen, including
                   centroid location, channel information, and phenotype information.
                2. `filename`, a filename for the DataFrame.
                3. `continuous_dataframe`, a DataFrame with continuous channel information if
                   continuous_also is true, otherwise this property is None.
        """
        extraction = self._extract(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
            continuous_also=continuous_also,
            retain_structure_id=retain_structure_id,
        )
        return extraction

    def _extract(self,
        specimen: str | None = None,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
        retain_structure_id: bool = False,
    ) -> dict[str, MatrixBundle]:
        if (specimen is None) == (study is None):
            raise ValueError('Must specify exactly one of specimen or study.')
        data_arrays = self._retrieve_expressions_from_database(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
            continuous_also=continuous_also,
        )
        centroid_coordinates = self._retrieve_structure_centroids_from_database(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
        )
        if study is None:
            assert specimen is not None
            study = retrieve_study_from_specimen(self.database_config_file, specimen)

        return self._create_feature_matrices(
            data_arrays,
            centroid_coordinates,
            self._retrieve_phenotypes(study),
            self._create_channel_information(data_arrays),
            retain_structure_id,
        )

    def _retrieve_expressions_from_database(self,
        specimen: str | None = None,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
    ) -> StudyDataArrays:
        logger.info('Retrieving expression data from database.')
        puller = SparseMatrixPuller(self.database_config_file)
        puller.pull(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
            continuous_also=continuous_also,
        )
        data_arrays = puller.get_data_arrays()
        logger.info('Done retrieving expression data from database.')
        return list(data_arrays.get_studies().values())[0]

    def _retrieve_structure_centroids_from_database(self,
        specimen: str | None = None,
        study: str | None = None,
        histological_structures: set[int] | None = None,
    ) -> StudyStructureCentroids:
        logger.info('Retrieving polygon centroids from shapefiles in database.')
        puller = StructureCentroidsPuller(self.database_config_file)
        puller.pull(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
        )
        structure_centroids = puller.get_structure_centroids()
        logger.info('Done retrieving centroids.')
        return list(structure_centroids.get_studies().values())[0]

    def _retrieve_phenotypes(self, study_name: str) -> dict[str, PhenotypeCriteria]:
        logger.info('Retrieving phenotypes from database.')
        phenotypes: dict[str, PhenotypeCriteria] = {}
        with DBCursor(database_config_file=self.database_config_file, study=study_name) as cursor:
            phenotype_access = PhenotypesAccess(cursor)
            for symbol_data in phenotype_access.get_phenotype_symbols(study_name):
                symbol = symbol_data.handle_string
                phenotypes[symbol] = phenotype_access.get_phenotype_criteria(study_name, symbol)
        logger.info('Done retrieving phenotypes.')
        return phenotypes

    def _create_feature_matrices(self,
        data_arrays: StudyDataArrays,
        centroid_coordinates: StudyStructureCentroids,
        phenotypes: dict[str, PhenotypeCriteria],
        channel_information: list[str],
        retain_structure_id: bool,
    ) -> dict[str, MatrixBundle]:
        logger.info('Creating feature matrices from binary data arrays and centroids.')
        matrices: dict[str, MatrixBundle] = {}
        data_arrays_by_specimen = cast(
            dict[str, dict[int, int]],
            data_arrays['data arrays by specimen'],
        )
        for j, specimen in enumerate(sorted(list(data_arrays_by_specimen.keys()))):
            logger.debug('Specimen %s .', specimen)
            expressions = data_arrays_by_specimen[specimen]
            coordinates = centroid_coordinates[specimen]
            assert expressions.keys() == coordinates.keys(), \
                f'Mismatched cells in expressions and coordinates ({len(expressions)} long vs. '\
                f'({len(coordinates)}).'
            rows = [
                self._create_feature_matrix_row(
                    coordinates[hs_id],
                    expression,
                    len(data_arrays['target index lookup']),
                ) for hs_id, expression in expressions.items()
            ]

            expected_length = len(rows[0])
            for row in rows:
                if expected_length != len(row):
                    lengths = (expected_length, len(row))
                    message = 'Expression vectors not all the same lengths (%s, %s).'
                    raise ValueError(message % lengths)

            dataframe = DataFrame(
                rows,
                columns=['pixel x', 'pixel y'] + [f'C {cs}' for cs in channel_information],
                index=tuple(expressions.keys()) if retain_structure_id else None,
            )
            for symbol, criteria in phenotypes.items():
                dataframe[f'P {symbol}'] = (
                    dataframe[[f'C {m}' for m in criteria.positive_markers]].all(axis=1) &
                    ~dataframe[[f'C {m}' for m in criteria.negative_markers]].any(axis=1)
                ).astype(int)
            matrices[specimen] = MatrixBundle(dataframe, f'{j}.tsv')

        if 'continuous data arrays by specimen' in data_arrays:
            continuous_data_arrays_by_specimen = cast(
                dict[str, dict[int, list[float]]],
                data_arrays['continuous data arrays by specimen'],
            )
            specimens = list(continuous_data_arrays_by_specimen.keys())
            for specimen in sorted(specimens):
                logger.debug('Specimen %s .', specimen)
                expression_vectors = continuous_data_arrays_by_specimen[specimen]
                dataframe = DataFrame(
                    expression_vectors.values(),
                    columns=[f'C {cs}' for cs in channel_information],
                    index=tuple(expression_vectors.keys()) if retain_structure_id else None,
                )
                matrices[specimen].continuous_dataframe = dataframe

        logger.info('Done creating feature matrices.')
        return matrices

    @staticmethod
    def _create_feature_matrix_row(
        centroid: tuple[float, float],
        binary: int,
        number_channels: int,
    ) -> list[float | int]:
        template = '{0:0%sb}' % number_channels   # pylint: disable=consider-using-f-string
        feature_vector = cast(list[float | int], [int(value) for value in list(template.format(binary)[::-1])])
        if number_channels != len(feature_vector):
            message = f'Expected binary-encoded integer {binary} to represent {number_channels} channels.'
            raise ValueError(message)
        return cast(list[float | int], list(centroid)) + feature_vector

    def _create_channel_information(self,
        study_information: dict[str, dict[str, Any]]
    ) -> list[str]:
        logger.info('Aggregating channel information for one study.')
        targets = {
            int(index): target
            for target, index in study_information['target index lookup'].items()
        }
        symbols = {
            target: symbol
            for symbol, target in study_information['target by symbol'].items()
        }
        logger.info('Done aggregating channel information.')
        return [
            symbols[targets[i]] for i in sorted([int(index) for index in targets.keys()])
        ]

    def extract_cohorts(self, study: str) -> dict[str, DataFrame]:
        """Extract specimen cohort information for every specimen in a study."""
        return self._extract_cohorts(study)

    def _extract_cohorts(self, study: str) -> dict[str, DataFrame]:
        stratification = self._retrieve_derivative_stratification_from_database()
        for substudy in self._retrieve_component_studies(study):
            if substudy in stratification:
                break
        else:
            raise RuntimeError('Stratification substudy not found for study.')
        return stratification[substudy]

    def _retrieve_derivative_stratification_from_database(self) -> Stratification:
        logger.info('Retrieving stratification from database.')
        puller = StratificationPuller(self.database_config_file)
        puller.pull(measured_only=True)
        stratification = puller.get_stratification()
        logger.info('Done retrieving stratification.')
        return stratification

    def _retrieve_component_studies(self, study: str) -> set[str]:
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
            cursor.execute(f'''
                SELECT component_study
                FROM study_component
                WHERE primary_study = '{study}';
            ''')
            rows = cursor.fetchall()
        lookup: set[str] = set()
        for row in rows:
            lookup.add(row[0])
        return lookup
