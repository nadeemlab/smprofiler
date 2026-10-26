"""Train atlas-reference models end-to-end on a tiny real-atlas subset.

The fixture in ``tiny_atlas/`` is a ~1200-usable-cell, 12-gene extract of the
real Allen Institute Human Immune Health Atlas (see ``tiny_atlas/README.md``),
plus the SMProfiler-channel → atlas-gene mapping and a one-study dataset. The
three smprofiler API calls the planner makes (channel annotations, study
availability, per-study channels) are stubbed so the test runs offline. This
exercises the full pipeline: plan, Parquet load, training, ONNX export and
validation, metadata.
"""
import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from smprofiler.atlas import training
from smprofiler.atlas.cache import StandaloneSQLiteHTTPCache
from smprofiler.atlas.inference import load_model, predict_z_score
from smprofiler.atlas.model_selection_fitting import STD_METHODS, predict_with_std
from smprofiler.atlas.study_channels import StudyChannel, StudyOrderedChannels

FIXTURE = Path(__file__).parent / 'tiny_atlas'
IDENTITY_CHANNELS = {'CD8', 'CD20', 'CD31', 'CD68', 'CD14', 'CD19', 'CD56'}
FUNCTIONAL_TARGETS = {'FOXP3', 'MKI67', 'GZMB', 'PD1', 'TIM3'}
MODEL_TYPES = set(STD_METHODS)


def _stub_annotations_api(base_url, timeout=30):
    """Stand in for /channel-annotations/ and /channel-aliases/."""
    return set(IDENTITY_CHANNELS), {}


def _stub_is_available(study, collection, base_url):
    """Stand in for /study-names/."""
    return True


def _stub_study_channels(studies, identity_channels, aliases, smprofiler_to_atlas, base_url, timeout=30):
    """Stand in for /channels/?study=...: every fixture channel, in TSV order."""
    with open(FIXTURE / 'smprofiler_channels_to_atlas.tsv', newline='') as f:
        rows = list(csv.DictReader(f, delimiter='\t'))
    channels = [
        StudyChannel(r['SMProfiler channel name'], r['SMProfiler channel name'], r['Atlas gene name'])
        for r in rows
    ]
    identity = tuple(c for c in channels if c.smprofiler_normalized in identity_channels)
    functional = tuple(c for c in channels if c.smprofiler_normalized not in identity_channels)
    return tuple(StudyOrderedChannels(identity, functional) for _ in studies)


def test_train_atlas_models_on_tiny_subset():
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(training, 'load_channel_annotations_from_api', _stub_annotations_api), \
            patch.object(training, '_is_available', _stub_is_available), \
            patch.object(training, 'retrieve_all_study_channels_from_api', _stub_study_channels), \
            patch.object(StandaloneSQLiteHTTPCache, 'cache_filename', str(Path(tmp) / 'cache.sqlite')):
        output_dir = Path(tmp) / 'models'
        training.run(
            FIXTURE / 'cell_atlas_small.parquet',
            FIXTURE / 'smprofiler_channels_to_atlas.tsv',
            FIXTURE / 'datasets',
            output_dir,
            annotations_api_url='https://fixture.local/api',  # stubbed; never fetched
            cv_folds=3,
        )

        study_dir = output_dir / 'test_study'
        produced = {p.stem for p in study_dir.glob('*.onnx')}
        assert produced == FUNCTIONAL_TARGETS, produced
        assert not list(study_dir.glob('*.pkl')), 'pickled models are deprecated'

        for target in produced:
            for extension in ('onnx', 'meta.json'):
                artifact = study_dir / f'{target}.{extension}'
                assert artifact.is_file() and artifact.stat().st_size > 0, artifact

            meta = json.loads((study_dir / f'{target}.meta.json').read_text())
            assert meta['study'] == 'test_study'
            assert meta['target_channel'] == target
            assert meta['input_channels'], 'expected non-empty identity features'
            assert set(meta['input_channels']).issubset(IDENTITY_CHANNELS), meta['input_channels']
            assert meta['model_type'] in MODEL_TYPES, meta['model_type']
            assert meta['std_method'] == STD_METHODS[meta['model_type']], meta['std_method']
            assert meta['onnx_input_dtype'] == 'float32'
            assert meta['onnx_has_std'] is True
            assert meta['onnx_inputs'] == ['X', 'measured'] and meta['onnx_outputs'] == ['z', 'mean', 'std']
            assert isinstance(meta['test_r2'], float)
            assert isinstance(meta['tree_calibration'], float)
            assert meta['atlas_version']

            _assert_model_scores_raw_cells(study_dir / f'{target}.onnx', len(meta['input_channels']))


def _assert_model_scores_raw_cells(onnx_path: Path, number_identity: int) -> None:
    session = load_model(str(onnx_path))
    rng = np.random.default_rng(0)
    identity = rng.gamma(2.0, 5.0, size=(6, number_identity))
    identity[3] = 0.0
    z = predict_z_score(session, identity, rng.gamma(2.0, 1.0, size=6))
    assert z.shape == (6,)
    assert np.isnan(z[3]) and np.all(np.isfinite(np.delete(z, 3))), z


def test_predict_with_std_rejects_non_input_dependent_models():
    for disallowed in ('ridge', 'elastic_net', 'huber', 'xgboost', 'gaussian_process'):
        try:
            predict_with_std(model=None, model_name=disallowed, X_normalized=None)
        except ValueError:
            continue
        raise AssertionError(f'predict_with_std should reject "{disallowed}"')


def main():
    test_predict_with_std_rejects_non_input_dependent_models()
    test_train_atlas_models_on_tiny_subset()
    print('atlas training on tiny real-atlas subset: OK')


if __name__ == '__main__':
    main()
