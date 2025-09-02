"""Design parameters for a tabular dataset to be imported by the main import workflow."""

from typing import cast

from pandas import read_csv

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class MissingPositivityColumnError(ValueError):
    """Raised when columns indicating dichotomized value for a phenotype are not all present."""


class TabularCellMetadataDesign:
    """This class provides the schema necessary to interpret cell metadata manifests."""

    def __init__(self,
        channels_file: str = '',
        **kwargs,  # pylint: disable=unused-argument
    ):
        self.channels = read_csv(
            channels_file,
            keep_default_na=False,
        )

    @staticmethod
    def get_cell_manifest_descriptor():
        return 'Tabular cell manifest'

    @staticmethod
    def validate_cell_manifest_descriptor(descriptor):
        return descriptor in [TabularCellMetadataDesign.get_cell_manifest_descriptor(),]

    def get_channel_names(self):
        return list(self.channels['Name'])

    def get_box_limit_column_names(self):
        xmin = 'XMin'
        xmax = 'XMax'
        ymin = 'YMin'
        ymax = 'YMax'
        return [xmin, xmax, ymin, ymax]

    def _get_indicator_prefix(self,
        phenotype_name,
        metadata_file_column='Column header fragment prefix',
    ):
        """Args:
            phenotype_name (str):
                One of the elementary phenotype names.
            metadata_file_column (str):
                The name of the column of the elementary phenotypes metadata file to
                search through.

        Returns:
            str:
                The prefix which appears in many CSV column names, for which these
                columns pertain to the given phenotype.
        """
        row = self.channels.loc[self.channels['Name'] == phenotype_name].squeeze()
        value = row[metadata_file_column]
        return str(value)

    def munge_name(self, signature):
        """Args:
            signature (dict):
                The keys are typically phenotype names and the values are "+" or "-". If
                a key is not a phenotype name, it is presumed to be the exact name of
                one of the columns in the tabular CSV. In this case the value
                should be an exact string of one of the cell values of this CSV.

        Returns:
            str:
                A de-facto name for the class delineated by this signature, obtained by
                concatenating key/value pairs in a standardized order.
        """
        keys = sorted(list(signature.keys()))
        feature_list = [key + signature[key] for key in keys]
        name = ''.join(feature_list)
        return name

    def get_feature_name(self, key, separator=' '):
        """Args:
            key (str):
                A phenotype/channel name (usually).

        Returns:
            str:
                The exact column name for the column in the tabular CSV which
                indicates (boolean) thresholded positivity for the given phenotype.
                If the key is not a phenotype name, then the key is returned unchanged.
        """
        if key in self.get_channel_names():
            return separator.join([self._get_indicator_prefix(key), 'Positive'])
        return key

    def get_intensity_feature_name(self, key, separator=' '):
        """Args:
            key (str):
                A phenotype/channel name (usually).

        Returns:
            str:
                The exact column name for the column in the tabular CSV which
                indicates (boolean) thresholded positivity for the given phenotype.
                If the key is not a phenotype name, then the key is returned unchanged.
        """
        if key in self.get_channel_names():
            return separator.join([self._get_indicator_prefix(key), 'Intensity'])
        return key

    def get_specific_columns(self, symbols, columns, column_getter):
        specific_columns = None
        missing = []
        for separator in [' ', '_']:
            _specific_columns = [
                cast(str, column_getter(symbol, separator=separator))
                for symbol in symbols
            ]
            _missing = [c for c in _specific_columns if not c in columns]
            if len(_missing) == 0:
                specific_columns = _specific_columns
                break
            missing = missing + _missing
            continue
        return specific_columns is not None, cast(list[str], specific_columns), missing

    def get_dichotomized_columns(self, symbols, columns):
        all_found, dichotomized_columns, missing = self.get_specific_columns(
            symbols,
            columns,
            self.get_feature_name,
        )
        if not all_found:
            raise MissingPositivityColumnError(f'Missing positivity columns: {missing}')
        return dichotomized_columns

    def get_intensity_columns(self, symbols, columns):
        all_found, intensity_columns, missing = self.get_specific_columns(
            symbols,
            columns,
            self.get_intensity_feature_name,
        )
        if not all_found:
            logger.warning('Did not find all "intensity" features: %s', missing)
        return intensity_columns

    def get_exact_column_names(self, requested_symbols, columns):
        dichotomized_columns = self.get_dichotomized_columns(requested_symbols, columns)
        intensity_columns = self.get_intensity_columns(requested_symbols, columns)
        feature_names = {symbol: [] for symbol in requested_symbols}
        for column, symbol in zip(dichotomized_columns, requested_symbols):
            feature_names[symbol].append(column)
        intensities_available = intensity_columns is not None
        if intensities_available:
            for column, symbol in zip(intensity_columns, requested_symbols):
                feature_names[symbol].append(column)
        return feature_names, intensities_available
