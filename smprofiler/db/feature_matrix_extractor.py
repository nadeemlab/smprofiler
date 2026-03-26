"""Convenience provision of a feature matrix for each study, retrieved from the SMProfiler database."""

from typing import cast, Any
from dataclasses import dataclass

from pandas import DataFrame

from smprofiler.ondemand.compressed_matrix_writer import CompressedMatrixWriter
from smprofiler.db.accessors.cells import CellsAccess
from smprofiler.db.accessors.cells import CellsData
from smprofiler.db.accessors.feature_names import get_ordered_feature_names_abstract
from smprofiler.db.database_connection import DBCursor
from smprofiler.db.database_connection import retrieve_study_from_specimen
from smprofiler.db.exchange_data_formats.metrics import PhenotypeCriteria
from smprofiler.db.accessors.phenotypes import PhenotypesAccess
from smprofiler.db.stratification_puller import (
    StratificationPuller,
    Stratification,
)
from smprofiler.ondemand.cache_store import get_cache_store
from smprofiler.ondemand.cache_store import CacheStore
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
    cache_store: CacheStore

    def __init__(self, database_config_file: str | None) -> None:
        self.database_config_file = database_config_file
        self.cache_store = get_cache_store(database_config_file)

    def extract(self,
        specimen: str,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
    ) -> dict[str, MatrixBundle]:
        """Extract feature matrices for a specimen.

        Parameters
        ----------
        specimen: str
            Which specimen to extract features for. 
        study: str | None = None
            The study may be inferrable.
        histological_structures: set[int] | None = None
            Which histological structures to extract features for from the given study or specimen,
            by their histological structure ID. Structures not found in either the provided
            specimen or study are ignored.
            The system for specifying these IDs should be 0-indexed scoped to the single specimen.
            If None, all structures are fetched.
        continuous_also: bool = False
            Whether to also calculate and return a DataFrame for each specimen with continuous
            channel information in addition to the default DataFrame which provides binary cast
            channel information.

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
        return {specimen: self._extract(
            specimen=specimen,
            study=study,
            histological_structures=histological_structures,
            continuous_also=continuous_also,
        )}

    def _extract(self,
        specimen: str,
        study: str | None = None,
        histological_structures: set[int] | None = None,
        continuous_also: bool = False,
    ) -> MatrixBundle:
        if study is None:
            study = retrieve_study_from_specimen(self.database_config_file, specimen)
        if histological_structures is None:
            ids = ()
        else:
            ids = tuple(histological_structures) 
        with DBCursor(database_config_file=self.database_config_file, study=study) as cursor:
            a = CellsAccess(cursor)
            location_phenotype, _ = a.get_cells_data(specimen, cell_identifiers=ids)
            if continuous_also:
                intensities = a.get_cells_data_intensity(specimen)
            else:
                intensities = None
        o = get_ordered_feature_names_abstract(study, self.cache_store)
        feature_names = tuple(map(lambda e: e.symbol, o.names))
        return self._create_feature_matrices(
            location_phenotype,
            intensities,
            self._retrieve_phenotypes(study),
            feature_names,
        )

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

    def _create_feature_matrices(
        self,
        location_phenotype: CellsData,
        intensities: CellsData | None,
        phenotypes: dict[str, PhenotypeCriteria],
        channel_information: tuple[str, ...],
    ) -> MatrixBundle:
        logger.info('Creating feature matrices from location/phenotype payload and intensities payload if available.')
        rows = CompressedMatrixWriter.parse_rows_location_phenotype(location_phenotype)
        channels = [f'C {cs}' for cs in channel_information]
        dataframe = DataFrame(rows, columns=['id', 'pixel x', 'pixel y'] + channels)
        if intensities is not None:
            rows = CompressedMatrixWriter.parse_rows_intensity(intensities, len(channel_information))
            i = DataFrame(rows, columns=['id'] + channels)
        else:
            i = None
        for symbol, criteria in phenotypes.items():
            dataframe[f'P {symbol}'] = (
                dataframe[[f'C {m}' for m in criteria.positive_markers]].all(axis=1) &
                ~dataframe[[f'C {m}' for m in criteria.negative_markers]].any(axis=1)
            ).astype(int)
        bundle = MatrixBundle(dataframe, '0.tsv')
        if i is not None:
            bundle.continuous_dataframe = i
        return bundle

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


