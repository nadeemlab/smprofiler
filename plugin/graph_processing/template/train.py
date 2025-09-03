#!/usr/bin/env python3
"""Train a model."""

from sys import path
from configparser import ConfigParser
from warnings import warn

path.append('/app')  # noqa
from train_cli import parse_arguments, DEFAULT_CONFIG_FILE
from util import HSGraph, GraphData, load_hs_graphs, save_hs_graphs


def _handle_random_seed_values(random_seed_value: str | None) -> int | None:
    if (random_seed_value is not None) and (str(random_seed_value).strip().lower() != "none"):
        return int(random_seed_value)
    return None


if __name__ == '__main__':
    args = parse_arguments()
    config_file = ConfigParser()
    config_file.read(args.config_file)
    random_seed: int | None = None
    if 'general' in config_file:
        random_seed = _handle_random_seed_values(config_file['general'].get('random_seed', None))
    if 'plugin' not in config_file:
        warn('No plugin section in config file. Using default values.')
        config_file.read(DEFAULT_CONFIG_FILE)
    config = config_file['plugin']

    smprofiler_graphs, _ = load_hs_graphs(args.input_directory)
