"""Convenience function for locating files listed in a file manifest describing an importable
CSV/TSV bundle.
"""

from pandas import read_csv

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def get_input_filenames_by_data_type(
    data_type: str | None = None,
    file_manifest_filename: str | None = None,
):
    """Retrieves from the file metadata table the names of all files with the given
    "Data type" field.

    :param data_type: The file type descriptor.
    :type data_type: str

    :return: The list of filenames.
    :rtype: list
    """
    if file_manifest_filename is None:
        raise ValueError('Need to supply file_manifest_filename.')
    file_metadata = read_csv(file_manifest_filename, sep='\t')
    records = file_metadata[file_metadata['Data type'] == data_type]
    return list(records['File name'])


def get_input_filename_by_identifier(
    input_file_identifier: str | None = None,
    file_manifest_filename: str | None = None,
) -> str | None:
    """Uses the file identifier to lookup the name of the associated file in the file
    metadata table, and cache the name of the associated file.

    :param file_metadata: The table of files.
    :type file_metadata: pd.DataFrame

    :param input_file_identifier: Key to search for in the "File ID" column of the
        file metadata table.
    :type input_file_identifier: str

    :return: The filename.
    :rtype: str
    """
    if file_manifest_filename is None:
        raise ValueError('Need to supply file_manifest_filename.')
    file_metadata = read_csv(file_manifest_filename, sep='\t')
    records = file_metadata[file_metadata['File ID'] == input_file_identifier]
    filenames = list(records['File name'])
    if len(filenames) > 1:
        logger.warning('File identifier "%s" duplicated.', input_file_identifier)
        return None
    if len(filenames) == 0:
        if not input_file_identifier == 'Compartments file':
            logger.warning('File identifier "%s" not found.', input_file_identifier)
        return None
    return filenames[0]
