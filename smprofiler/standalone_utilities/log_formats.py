"""Custom logger for general SMProfiler functionality."""
import logging
import re


class CustomFormatter(logging.Formatter):
    """A custom colorizing logger."""
    grey = '\x1b[38;21m'
    green = '\u001b[32m'
    bold_green = '\u001b[32;1m'
    magenta = '\u001b[35m'
    bold_magenta = '\u001b[35;1m'
    yellow = '\u001b[33m'
    bold_yellow = '\u001b[33;1m'
    red = '\u001b[31m'
    bold_red = '\u001b[31;1m'
    blue = '\u001b[34m'
    cyan = '\u001b[0;36m'
    div = '\u2503'
    reset = '\u001b[0m'

    FORMATS = {
        logging.DEBUG:    blue + '%(asctime)s ' + reset + magenta + '[ ' + reset +               "%(levelname)s" + reset + magenta +  ' ] ' + blue + "%(lineno)3s" + reset + ' ' + magenta + "%(name)-47s" + reset + cyan + div + reset + " %(message)s",
        logging.INFO:     blue + '%(asctime)s ' + reset + magenta + '[ ' + reset + bold_green  + "%(levelname)s" + reset + magenta + '  ] ' +                                                "%(name)-51s" + reset + cyan + div + reset + " %(message)s",
        logging.WARNING:  blue + '%(asctime)s ' + reset + magenta + '['  + reset + bold_yellow + "%(levelname)s" + reset + magenta +   '] ' + blue + "%(lineno)3d" + reset + ' ' + magenta + "%(name)-47s" + reset + cyan + div + reset + " %(message)s",
        logging.ERROR:    blue + '%(asctime)s ' + reset + magenta + '[ ' + reset + bold_red    + "%(levelname)s" + reset + magenta +  ' ] ' + blue + "%(lineno)3d" + reset + ' ' + magenta + "%(name)-47s" + reset + cyan + div + reset + " %(message)s",
        logging.CRITICAL: blue + '%(asctime)s ' + reset + magenta + '['  + reset + bold_red    + "%(levelname)s" + reset + magenta +   '] ' + blue + "%(lineno)3d" + reset + ' ' + magenta + "%(name)-47s" + reset + cyan + div + reset + " %(message)s",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, datefmt='%m-%d %H:%M:%S')
        return formatter.format(record)


def colorized_logger(name):
    """A lightweight customization of the Python standard library's ``logging`` module
    loggers, to provide colorized log messages.

    Args:
        name (str):
            The name of the logger to requisition. Typically a module's
            ``__name__`` attribute.

    Returns:
        The logger.
    """
    logger = logging.getLogger(re.sub(r'^smprofiler\.', '', name))
    level = logging.DEBUG
    logger.setLevel(level)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(CustomFormatter())
    logger.addHandler(stream_handler)
    return logger
