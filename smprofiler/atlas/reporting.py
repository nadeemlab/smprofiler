"""Progress reporting and logging helpers for atlas model training.

Per-module log messages use the codebase-standard ``colorized_logger``. This
module holds the few shared extras that pattern doesn't cover:

- ``section`` / ``subsection``: visual dividers for the CLI's human-facing
  progress output, printed (not logged) so they stand out from timestamped log
  lines and align with the final summary table (see ``training.run``). Printing
  such output matches the codebase (e.g. ``entry_point/cli.py``,
  ``db/scripts/status.py``).
- ``format_elapsed``: shared elapsed-time formatting, used across modules.
- ``suppress_third_party_logging`` / ``set_atlas_log_level``: standard-logging
  level tweaks for the ONNX libraries and the ``--verbose`` flag.
"""
import logging

# Width of visual separator lines.
_SEP_WIDTH = 70

# Third-party libraries that log verbosely during ONNX conversion / inference.
_NOISY_LOGGERS = ('skl2onnx', 'onnx', 'onnxruntime')


def section(title: str) -> None:
    """Print a prominent section header to stdout (bypasses log timestamps)."""
    bar = '═' * _SEP_WIDTH
    print(f'\n{bar}', flush=True)
    print(f'  {title}', flush=True)
    print(bar, flush=True)


def subsection(title: str) -> None:
    """Print a lighter sub-section divider."""
    print(f"\n{'─' * _SEP_WIDTH}", flush=True)
    print(f'  {title}', flush=True)
    print(f"{'─' * _SEP_WIDTH}", flush=True)


def format_elapsed(seconds: float) -> str:
    """Return a human-readable elapsed time string."""
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}h {minutes}m {secs}s'
    if minutes:
        return f'{minutes}m {secs}s'
    return f'{secs}s'


def suppress_third_party_logging() -> None:
    """Quiet the verbose ONNX ecosystem loggers down to WARNING."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def set_atlas_log_level(verbose: bool) -> None:
    """Set the verbosity of every ``smprofiler.atlas`` logger.

    ``colorized_logger`` configures each module logger at DEBUG; this gates
    DEBUG output behind the caller's ``--verbose`` choice without disturbing
    the shared colorized handler/format used across the codebase.
    """
    level = logging.DEBUG if verbose else logging.INFO
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and name.split('.')[0] == 'atlas':
            logger.setLevel(level)
            for handler in logger.handlers:
                handler.setLevel(level)
