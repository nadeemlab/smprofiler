"""Train atlas-reference models end-to-end on a tiny real-atlas subset.

The fixture in ``tiny_atlas/`` is a ~1200-usable-cell, 12-gene extract of the
real Allen Institute Human Immune Health Atlas (see ``tiny_atlas/README.md``),
plus the SPT-channel → atlas-gene mapping and a one-study dataset. Channel
annotations are normally fetched from the smprofiler API (the source of truth);
here the API loader is stubbed so the test runs offline. This exercises the full
pipeline — annotations, mapping, Parquet load, per-study plan, training, ONNX
export/validation, and metadata — without the 42 GB file or network access.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from smprofiler.atlas import training
from smprofiler.atlas.inference import load_model, predict_z_score

FIXTURE = Path(__file__).parent / "tiny_atlas"
IDENTITY_CHANNELS = {"CD8", "CD20", "CD31", "CD68", "CD14", "CD19", "CD56"}
FUNCTIONAL_TARGETS = {"FOXP3", "MKI67", "GZMB", "PD1", "TIM3"}
# Only architectures whose predictive std exports as a native second ONNX output.
MODEL_TYPES = {"bayesian_ridge", "gaussian_process"}


def _stub_annotations_api(base_url, timeout=30):
    """Stand in for the smprofiler API: return the fixture's channel annotations."""
    return set(IDENTITY_CHANNELS), set(FUNCTIONAL_TARGETS), {}


def _assert_onnx_has_two_outputs_and_z_scores(onnx_path: Path, n_identity: int) -> None:
    """The exported model must expose (mean, std) and drive the z-score path.

    A cell with zero identity sum has no reference and must be NaN; cells with a
    reference must be finite wherever the model's std is nonzero. (Std can be 0 on
    this degenerate tiny fixture when a query lands on a training point, which would
    make z infinite — that is a valid model output, not a failure.)
    """
    session = load_model(onnx_path.read_bytes())
    assert len(session.get_outputs()) == 2, [o.name for o in session.get_outputs()]
    rng = np.random.default_rng(0)
    identity = rng.random((6, n_identity)) + 0.1
    identity[0] = 0.0  # zero identity sum -> no reference
    measured = rng.random(6)
    z = predict_z_score(session, identity, measured)
    assert z.shape == (6,)
    assert np.isnan(z[0]), z  # undefined reference
    assert not np.isnan(z[1:]).any(), z  # defined references are not NaN


def test_train_atlas_models_on_tiny_subset():
    with tempfile.TemporaryDirectory() as tmp, \
            patch.object(training, "load_channel_annotations_from_api", _stub_annotations_api):
        output_dir = Path(tmp) / "models"
        training.run(
            FIXTURE / "cell_atlas_small.parquet",
            FIXTURE / "smprofiler_channels_to_atlas.tsv",
            FIXTURE / "datasets",
            output_dir,
            annotations_api_url="https://fixture.local/api",  # stubbed; never fetched
            cv_folds=3,
        )

        study_dir = output_dir / "test_study"
        produced = {p.stem for p in study_dir.glob("*.onnx")}
        # Every functional target has clear variance in the fixture, so all train.
        assert produced == FUNCTIONAL_TARGETS, produced

        for target in produced:
            # No .pkl any more: per-cell std comes from the ONNX std output, not Python.
            for extension in ("onnx", "meta.json"):
                artifact = study_dir / f"{target}.{extension}"
                assert artifact.is_file() and artifact.stat().st_size > 0, artifact
            assert not (study_dir / f"{target}.pkl").exists(), "pickle should no longer be written"

            meta = json.loads((study_dir / f"{target}.meta.json").read_text())
            assert meta["study"] == "test_study"
            assert meta["target_channel"] == target
            assert meta["input_channels"], "expected non-empty identity features"
            assert set(meta["input_channels"]).issubset(IDENTITY_CHANNELS), meta["input_channels"]
            assert meta["model_type"] in MODEL_TYPES, meta["model_type"]
            # Every selected model must provide an input-dependent std — never the
            # global residual std.
            assert meta["std_method"] in {"bayesian_posterior",
                                          "gaussian_posterior"}, meta["std_method"]
            expected_dtype = "float64" if meta["model_type"] == "gaussian_process" else "float32"
            assert meta["onnx_input_dtype"] == expected_dtype, meta["onnx_input_dtype"]
            # The ONNX model carries the std output, and the centering offset is recorded.
            assert meta["onnx_has_std"] is True, meta
            assert isinstance(meta["target_offset"], float)
            assert isinstance(meta["test_r2"], float)
            assert meta["atlas_version"]

            # The exported ONNX must actually have the two documented outputs, and the
            # inference z-score path must run on it.
            _assert_onnx_has_two_outputs_and_z_scores(study_dir / f"{target}.onnx",
                                                      len(meta["input_channels"]))


def test_predict_with_std_rejects_non_input_dependent_models():
    """The std-method guard must reject any architecture without input-dependent std."""
    from smprofiler.atlas.models import predict_with_std

    for disallowed in ("ridge", "elastic_net", "huber", "xgboost",
                       "random_forest", "extra_trees"):
        try:
            predict_with_std(model=None, model_name=disallowed, X_norm=None)
        except ValueError:
            continue
        raise AssertionError(f"predict_with_std should reject '{disallowed}'")


def main():
    test_predict_with_std_rejects_non_input_dependent_models()
    test_train_atlas_models_on_tiny_subset()
    print("atlas training on tiny real-atlas subset: OK")


if __name__ == "__main__":
    main()
