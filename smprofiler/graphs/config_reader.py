"""Reads the data extraction and graph generation configuration files and all parameters."""

from configparser import ConfigParser
from typing import Any

GENERAL_SECTION_NAME = 'general'
EXTRACT_SECTION_NAME = 'extract'
GENERATION_SECTION_NAME = 'graph-generation'
UPLOAD_SECTION_NAME = 'upload-importances'
PLOT_FRACTIONS_SECTION_NAME = 'plot-importance-fractions'


def _read_config_file(
    config_file_path: str | None,
    section: str,
    config_file_string: str | None = None,
) -> dict[str, Any]:
    config_file = ConfigParser()
    if config_file_path is not None:
        config_file.read(config_file_path)
    elif config_file_string is not None:
        config_file.read_string(config_file_string)
    else:
        raise ValueError("Either config_file_path or config_file_string must be provided.")
    config: dict[str, Any] = \
        dict(config_file[GENERAL_SECTION_NAME]) if (GENERAL_SECTION_NAME in config_file) else {}
    if section in config_file:
        config.update(dict(config_file[section]))
    for sec in config_file.sections():
        if sec.startswith(section + '.'):
            sub_section = sec.split('.')[1]
            config[sub_section] = dict(config_file[sec])
    for key, value in config.items():
        if isinstance(value, str) and value.lower() in {'none', 'null', ''}:
            config[key] = None
    return config


def read_extract_config(config_file_path: str) -> tuple[
    str,
    str,
    list[int] | None,
]:
    f"""Read the TOML config file and return the '{EXTRACT_SECTION_NAME}' section.

    For a detailed explanation of the return values, refer to the docstring of
    `smprofiler.graphs.extract.extract()`.
    """
    config = _read_config_file(config_file_path, EXTRACT_SECTION_NAME)
    db_config_file_path: str = config["db_config_file_path"]
    study_name: str = config["study_name"]
    strata_str = config.get("strata", None)
    strata: list[int] | None = \
        [int(x) for x in strata_str.split()] if (strata_str is not None) else None
    return (
        db_config_file_path,
        study_name,
        strata,
    )


def read_generation_config(config_file_path: str) -> tuple[
    int,
    int,
    bool,
    bool,
    int | None,
    int | None,
    bool,
    str | None,
    int,
    int,
    int | None,
    int | None,
]:
    f"""Read the TOML config file and return the '{GENERATION_SECTION_NAME}' section.

    For a detailed explanation of the return values, refer to the docstring of
    `smprofiler.graphs.generate_graphs.generate_graphs()`.
    """
    config = _read_config_file(config_file_path, GENERATION_SECTION_NAME)

    validation_data_percent_str = config.get("validation_data_percent", "0")
    validation_data_percent: int = int(validation_data_percent_str)

    test_data_percent_str = config.get("test_data_percent", "0")
    test_data_percent: int = int(test_data_percent_str)

    use_channels_str = config.get("use_channels", "True")
    use_channels: bool = bool(use_channels_str)

    use_phenotypes_str = config.get("use_phenotypes", "True")
    use_phenotypes: bool = bool(use_phenotypes_str)

    roi_side_length_str = config.get("roi_side_length", None)
    roi_side_length: int | None = \
        None if (roi_side_length_str is None) else int(roi_side_length_str)

    cells_per_roi_target_str = config.get("cells_per_roi_target", 5_000)
    cells_per_roi_target: int | None = \
        None if (cells_per_roi_target_str is None) else int(cells_per_roi_target_str)

    max_cells_to_consider: int = int(config.get("max_cells_to_consider", 100_000))

    target_name_str = config.get("target_name", None)
    target_name: str | None = None if (target_name_str is None) else target_name_str

    exclude_unlabeled_str = config.get("exclude_unlabeled", "True")
    exclude_unlabeled: bool = bool(exclude_unlabeled_str)

    n_neighbors: int = int(config.get("n_neighbors", 5))

    threshold_str = config.get("threshold", None)
    threshold: int | None = None if (threshold_str is None) else int(threshold_str)

    random_seed_str = config.get("random_seed", None)
    random_seed: int | None = None if (random_seed_str is None) else int(random_seed_str)

    return (
        validation_data_percent,
        test_data_percent,
        use_channels,
        use_phenotypes,
        roi_side_length,
        cells_per_roi_target,
        exclude_unlabeled,
        target_name,
        max_cells_to_consider,
        n_neighbors,
        threshold,
        random_seed,
    )


def read_upload_config(config_file_path: str) -> tuple[
    str,
    str,
    str,
    str,
    str | None,
    str | None,
]:
    f"""Read the TOML config file and return the '{UPLOAD_SECTION_NAME}' section.

    For a detailed explanation of the return values, refer to the docstring of
    `smprofiler.db.importance_score_transcriber.transcribe_importance()`.
    """
    config = _read_config_file(config_file_path, UPLOAD_SECTION_NAME)
    db_config_file_path: str = config["db_config_file_path"]
    study_name: str = config["study_name"]
    plugin_used: str = config["plugin_used"]
    datetime_of_run: str = config["datetime_of_run"]
    plugin_version = config.get("plugin_version", None)
    cohort_stratifier = config.get("cohort_stratifier", None)
    return (
        db_config_file_path,
        study_name,
        plugin_used,
        datetime_of_run,
        plugin_version,
        cohort_stratifier,
    )


def read_plot_importance_fractions_config(
    config_file_path: str | None,
    config_file_string: str | None = None,
    calling_by_api: bool = False,
) -> tuple[
    str,
    str,
    list[str],
    list[tuple[int, str]],
    list[str],
    tuple[int, int],
    str | None,
]:
    f"""Read the TOML config file and return the '{PLOT_FRACTIONS_SECTION_NAME}' section.

    For a detailed explanation of the return values, refer to the docstring of
    `smprofiler.graphs.importance_fractions.PlotGenerator()`.
    """
    config = _read_config_file(config_file_path, PLOT_FRACTIONS_SECTION_NAME, config_file_string)
    host_name: str = config.get("host_name", "http://smprofiler.io/api")
    study_name: str = config["study_name"] if not calling_by_api else ''
    phenotypes: list[str] = config['phenotypes'].split(', ')
    plugins: list[str] = config['plugins'].split(', ')
    try:
        figure_size: tuple[int, int] = tuple(map(int, config['figure_size'].split(', ')))
    except ValueError as e:
        raise ValueError("figure_size must be a two-tuple of integers.") from e
    assert len(figure_size) == 2, "figure_size must be a two-tuple of integers."
    orientation: str | None = config.get("orientation", None)

    cohorts: list[tuple[int, str]] = []
    i_cohort: int = 0
    cohort_section_name: str = f'cohort0'
    while cohort_section_name in config:
        cohort = config[cohort_section_name]
        try:
            cohorts.append((int(cohort['index_int']), cohort['label']))
        except KeyError:
            'Each cohort must have an index_int and a label.'
        except ValueError:
            'Cohort index_int must be an integer.'
        i_cohort += 1
        cohort_section_name = f'cohort{i_cohort}'
    return (
        host_name,
        study_name,
        phenotypes,
        cohorts,
        plugins,
        figure_size,
        orientation,
    )
