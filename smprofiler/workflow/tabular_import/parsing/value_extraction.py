"""Convenience utility for retrieving a unique value from a dataframe column."""
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


def get_unique_value(dataframe, column):
    handles = sorted(list(set(dataframe[column]).difference([''])))
    if len(handles) == 0:
        message = f'No "{column}" values are supplied for this run.'
        logger.error(message)
        raise ValueError(message)
    if len(handles) > 1:
        message = 'Multiple "%s" values were supplied for this run. Using "%s".'
        logger.warning(message, column, handles[0])
    return handles[0]
