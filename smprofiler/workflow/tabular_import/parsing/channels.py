"""Source file parsing for imaging/feature-assessment channel metadata."""
from typing import cast
import re

from pandas import DataFrame
from pandas import Series
from pandas import read_csv
from psycopg import cursor as PsycopgCursor

from smprofiler.db.source_file_parser_interface import SourceToADIParser
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

class ChannelsPhenotypesParser(SourceToADIParser):
    """Source file parsing for imaging/feature-assessment channel metadata."""
    def parse(self,
        connection,
        channels_file,
        phenotypes_file,
        study_name,
    ):
        """Retrieve the phenotype and channel metadata, and parse records for:
        - chemical species
        - biological marking system
        - data analysis study
        - cell phenotype
        - cell phenotype criterion
        """
        channels = read_csv(channels_file, sep=',', na_filter=False, dtype=str)
        phenotypes = read_csv(phenotypes_file, sep=',', na_filter=False, dtype=str)

        data_analysis_study = SourceToADIParser.get_data_analysis_study_name(study_name)
        measurement_study = SourceToADIParser.get_measurement_study_name(study_name)

        cursor = connection.cursor()

        chemical_species_identifiers_by_symbol = self._handle_chemical_species(channels, cursor)

        self._handle_marking_system(
            channels,
            measurement_study,
            chemical_species_identifiers_by_symbol,
            cursor,
        )

        query = self.generate_basic_insert_query('data_analysis_study')
        cursor.execute(query, (data_analysis_study, ))

        self._handle_phenotypes(
            phenotypes,
            chemical_species_identifiers_by_symbol,
            data_analysis_study,
            cursor,
        )
        logger.info('Parsed records implied by "%s" and "%s".', channels_file, phenotypes_file)
        connection.commit()
        cursor.close()
        return chemical_species_identifiers_by_symbol

    def _handle_chemical_species(self,
        channels: DataFrame,
        cursor: PsycopgCursor,
    ) -> dict[str, str]:
        identifier = self._get_next('chemical_species', cursor)
        initial_value = identifier
        chemical_species_identifiers_by_symbol: dict[str, str] = {}
        for _, phenotype in channels.iterrows():
            symbol = phenotype['Name']
            chemical_structure_class = phenotype['Target structure class']
            record = (
                str(identifier),
                symbol,
                phenotype['Target full name'],
                chemical_structure_class,
            )
            was_found, key = self.check_exists('chemical_species', record, cursor)
            if not was_found:
                cursor.execute(
                    self.generate_basic_insert_query('chemical_species'),
                    record,
                )
                chemical_species_identifiers_by_symbol[symbol] = str(identifier)
                identifier = identifier + 1
            else:
                chemical_species_identifiers_by_symbol[symbol] = key
                logger.debug(
                    '"chemical_species" %s already exists.',
                    str([''] + list(record[1:])),
                )
        logger.info('Saved %s chemical species records.', identifier - initial_value)
        return chemical_species_identifiers_by_symbol

    def _handle_marking_system(self,
        channels: DataFrame,
        measurement_study: str,
        chemical_species_identifiers_by_symbol: dict[str, str],
        cursor: PsycopgCursor,
    ):
        identifier = self._get_next('biological_marking_system', cursor)
        initial_value = identifier
        for _, phenotype in channels.iterrows():
            symbol = phenotype['Name']
            record = (
                str(identifier),
                str(chemical_species_identifiers_by_symbol[symbol]),
                phenotype['Antibody'],
                phenotype['Marking mechanism'],
                measurement_study,
            )
            was_found, _ = self.check_exists('biological_marking_system', record, cursor)
            if not was_found:
                cursor.execute(self.generate_basic_insert_query('biological_marking_system'),record)
                identifier = identifier + 1
            else:
                message = '"biological_marking_system" %s already exists.'
                logger.debug(message, str([''] + list(record[1:])))
        logger.info('Saved %s biological marking system records.', identifier - initial_value)

        mechanism = self._infer_common_marking_mechanism(channels)
        query = 'UPDATE specimen_measurement_study SET assay=%s WHERE name=%s ;'
        cursor.execute(query, (mechanism, measurement_study))

    def _handle_phenotypes(self,
        phenotypes: DataFrame,
        chemical_species_identifiers_by_symbol: dict[str, str],
        data_analysis_study: str,
        cursor: PsycopgCursor,
    ) -> None:
        identifier = self._get_next('cell_phenotype', cursor)
        initial_value = identifier
        cell_phenotype_identifiers_by_symbol: dict[str, int] = {}
        for _, phenotype in phenotypes.iterrows():
            symbol, phenotype_identifier, _identifier, signature = self._handle_phenotype(
                phenotype,
                chemical_species_identifiers_by_symbol,
                identifier,
                cursor,
            )
            identifier = _identifier
            cell_phenotype_identifiers_by_symbol[symbol] = phenotype_identifier
            self._handle_signature(signature, phenotype_identifier, data_analysis_study, cursor)
        logger.info('Saved %s cell phenotype records.', identifier - initial_value)

    def _handle_phenotype(self,
        phenotype: Series,
        chemical_species_identifiers_by_symbol: dict[str, str],
        identifier: int,
        cursor: PsycopgCursor,
    ) -> tuple[str, int, int, list[tuple[str, str]]]:
        symbol = phenotype['Name']
        record: tuple[str, ...] = (str(identifier), symbol, symbol)
        was_found, key = self.check_exists('cell_phenotype', record, cursor)
        if not was_found:
            cursor.execute(self.generate_basic_insert_query('cell_phenotype'), record)
            phenotype_identifier = identifier
            identifier = identifier + 1
            logger.debug('Recognized phenotype: %s', symbol)
        else:
            phenotype_identifier = key
            logger.debug('"cell_phenotype" %s already exists.', str([''] + list(record[1:])))

        signature = self._create_signature(phenotype, chemical_species_identifiers_by_symbol)
        return symbol, phenotype_identifier, identifier, signature

    def _create_signature(self,
        phenotype: Series,
        chemical_species_identifiers_by_symbol: dict[str, str],
    ) -> list[tuple[str, str]]:
        positive_markers = set(str(phenotype['Positive markers']).split(';')).difference([''])
        negative_markers = set(str(phenotype['Negative markers']).split(';')).difference([''])
        symbols = chemical_species_identifiers_by_symbol.keys()
        missing = positive_markers.union(negative_markers).difference(symbols)
        if len(missing) > 0:
            logger.warning(
                'Markers %s are part of phenotype %s but do not represent '
                'any known "chemical_species". This marker is skipped.',
                missing,
                phenotype,
            )
        signature = [
            ('positive', chemical_species_identifiers_by_symbol[m])
            for m in set(positive_markers).difference(missing)
        ] + [
            ('negative', chemical_species_identifiers_by_symbol[m])
            for m in set(negative_markers).difference(missing)
        ]
        return cast(list[tuple[str, str]], signature)

    def _handle_signature(self,
        signature: list[tuple[str, str]],
        phenotype_identifier: int,
        data_analysis_study: str,
        cursor: PsycopgCursor,
    ) -> None:
        for polarity, chemical_species_identifier in signature:
            record = (
                str(phenotype_identifier),
                chemical_species_identifier,
                polarity,
                data_analysis_study,
            )
            was_found, _ = self.check_exists(
                'cell_phenotype_criterion',
                record,
                cursor,
                no_primary=True,
            )
            if not was_found:
                cursor.execute(self.generate_basic_insert_query('cell_phenotype_criterion'), record)
            else:
                logger.debug('"cell_phenotype_criterion" %s already exists.', str(record))

    @staticmethod
    def _get_next(*args) -> int:
        return SourceToADIParser.get_next_integer_identifier(*args)

    @staticmethod
    def _infer_common_marking_mechanism(channels: DataFrame) -> str:
        mechanisms = list(set(row['Marking mechanism'] for i, row in channels.iterrows()))
        if len(mechanisms) > 1:
            logger.warning('Encountered multiple marking mechanisms: %s', mechanisms)
            computational = [m for m in mechanisms if re.search('[Cc]omputational [Ii]dentification', m)]
            for mechanism in computational:
                logger.info(f'Excluding "{mechanism}" as computationally-generated, not the primary marking mechanism.')
                mechanisms.remove(mechanism)
        if len(mechanisms) == 1:
            mechanism = mechanisms[0]
        else:
            mechanism = ChannelsPhenotypesParser._get_most_common_marking_mechanism(channels)
        logger.info('Inferred marking mechanism: %s', mechanism)
        return mechanism

    @classmethod
    def _get_most_common_marking_mechanism(cls, channels: DataFrame) -> str:
        frequencies = list(channels.value_counts('Marking mechanism').items())
        frequencies = sorted(frequencies, key=lambda row: row[1], reverse=True)
        return str(frequencies[0][0])
