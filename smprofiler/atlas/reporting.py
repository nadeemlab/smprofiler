"""Progress reporting and logging helpers for atlas model training.

These are presentation concerns kept apart from the training logic: section
dividers printed straight to stdout (so they read cleanly alongside tqdm
progress bars), an elapsed-time formatter, a file-descriptor silencer for
noisy C-extension output, and helpers to tune log verbosity.
"""
import contextlib
import logging
import os

# Width of visual separator lines.
_SEP_WIDTH = 70

# Third-party libraries that log verbosely during ONNX conversion / inference.
_NOISY_LOGGERS = ('skl2onnx', 'onnx', 'onnxruntime')


@contextlib.contextmanager
def silence_output():
    """Redirect OS-level stdout/stderr to /dev/null (suppresses C-ext prints)."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        os.close(devnull)


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
