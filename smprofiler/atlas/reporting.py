"""
Progress reporting and logging helpers for atlas model training.
"""
import logging

_SEPARATOR_WIDTH = 70

_NOISY_LOGGERS = ('skl2onnx', 'onnx', 'onnxruntime')


def section(title: str) -> None:
    bar = '═' * _SEPARATOR_WIDTH
    print(f'\n{bar}', flush=True)
    print(f'  {title}', flush=True)
    print(bar, flush=True)

def subsection(title: str) -> None:
    print(f"\n{'─' * _SEPARATOR_WIDTH}", flush=True)
    print(f'  {title}', flush=True)
    print(f"{'─' * _SEPARATOR_WIDTH}", flush=True)

def format_elapsed(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f'{hours}h {minutes}m {secs}s'
    if minutes:
        return f'{minutes}m {secs}s'
    return f'{secs}s'

def suppress_third_party_logging() -> None:
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

def set_atlas_log_level(verbose: bool) -> None:
    """
    Set the verbosity of every ``smprofiler.atlas`` logger.
    """
    level = logging.DEBUG if verbose else logging.INFO
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and name.split('.')[0] == 'atlas':
            logger.setLevel(level)
            for handler in logger.handlers:
                handler.setLevel(level)

