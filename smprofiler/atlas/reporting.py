"""
Progress reporting and logging helpers for atlas model training.
"""
import time
import logging

from smprofiler.atlas.types import TrainingProgress
from smprofiler.atlas.types import TrainingOptions
from smprofiler.atlas.types import TrainingPlan
from smprofiler.atlas.types import STD_METHODS
from smprofiler.atlas.types import SelectedModel
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


_SEPARATOR_WIDTH = 70

_NOISY_LOGGERS = ('skl2onnx', 'onnx', 'onnxruntime')

_SUMMARY_WIDTH = 70


def section(title: str) -> None:
    bar = '═' * _SEPARATOR_WIDTH
    print(f'\n{bar}', flush=True)
    print(f'  {title}', flush=True)
    print(bar, flush=True)

def subsection(title: str) -> None:
    print(f"\n{'-' * _SEPARATOR_WIDTH}", flush=True)
    print(f'  {title}', flush=True)
    print(f"{'-' * _SEPARATOR_WIDTH}", flush=True)

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

def report_execution_summary(run_start, options: TrainingOptions, progress: TrainingProgress):
    total_elapsed = format_elapsed(time.monotonic() - run_start)
    section(f'Training complete - {progress.model_counter} models in {total_elapsed}')
    print(f'Number of ONNX models validated against sklearn original, prediction: {progress.number_validated}')
    print(f'Number of ONNX models validated against sklearn original, standard deviation prediction: {progress.number_validated_std}')

    def _shorten(string: str, to: int = 23) -> str:
        return string[0:min(len(string), to)]

    if progress.summary_rows:
        header = (f'  {"Study":<24}  {"Target":<16}  {"Model":<24}  {"Std method":<22}'
                  f'  {"cv_R²":>8}  {"test_R²":>8}  {"test_MAE":>10}  {"KB":>6}')
        print(header, flush=True)
        print('  ' + '-' * (_SUMMARY_WIDTH - 2), flush=True)
        for row in progress.summary_rows:
            print(
                f'  {_shorten(row["study"]):<24}  {row["target_channel"]:<16}  {row["architecture_type"]:<24}'
                f'  {row["std_method"]:<22}'
                f'  {row["cv_r2"]:>8.4f}  {row["test_r2"]:>8.4f}'
                f'  {row["test_mae"]:>10.4f}  {row["onnx_kb"]:>6}',
                flush=True,
            )
    print(f'\nModels saved to: {options.output_directory.resolve()}', flush=True)


def report_plan(plan: TrainingPlan) -> None:
    section('Training plan')
    total_models = sum(len(p.get_channels('functional')) for p in plan)
    for p in plan:
        subsection(f'Study: {p.study_handle}')
        identity = p.get_channels('identity')
        logger.info(
            '  Identity features (%d): %s', len(identity), identity
        )
        functional = p.get_channels('functional')
        for fc in functional:
            logger.info(' => model: target="%s"  features=%s', fc.study_specific_name, list(map(lambda c: c.study_specific_name, identity)))
    print(f'\nTotal: {len(plan)} studies, {total_models} models to train.', flush=True)


def report_plan_options(plan: TrainingPlan, options: TrainingOptions) -> None:
    total_models = sum(len(p.get_channels('functional')) for p in plan)
    section(
        f'Atlas-reference model training -- '
        f'{len(plan)} studies, {total_models} models total'
    )
    logger.info('Output directory: %s', options.output_directory.resolve())
    if options.max_cells:
        logger.info('Max atlas cells per study: %s', f'{options.max_cells:,}')
    else:
        logger.info('Using full atlas (no cell limit)')
    logger.info('Cross-validation folds: %d', options.cv_folds)


def report_model_stats(selected: SelectedModel) -> None:
    logger.info(
        '  Result   : model="%s"  test_R²=%.4f  test_MAE=%.4f'
        '  std_method=%s  global_std=%.4f  [%s]',
        selected.name,
        selected.test_r2,
        selected.test_mae,
        STD_METHODS[selected.name],
        selected.global_std,
        selected.training_time_formatted,
    )

