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

from smprofiler.atlas import training

FIXTURE = Path(__file__).parent / "tiny_atlas"
IDENTITY_CHANNELS = {"CD8", "CD20", "CD31", "CD68", "CD14", "CD19", "CD56"}
FUNCTIONAL_TARGETS = {"FOXP3", "MKI67", "GZMB", "PD1", "TIM3"}
MODEL_TYPES = {"extra_trees", "random_forest", "bayesian_ridge", "gaussian_process"}


def _stub_annotations_api(base_url, timeout=30):
    """Stand in for the smprofiler API: return the fixture's channel annotations."""
    return set(IDENTITY_CHANNELS), set(FUNCTIONAL_TARGETS), {}


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
            for extension in ("onnx", "pkl", "meta.json"):
                artifact = study_dir / f"{target}.{extension}"
                assert artifact.is_file() and artifact.stat().st_size > 0, artifact

            meta = json.loads((study_dir / f"{target}.meta.json").read_text())
            assert meta["study"] == "test_study"
            assert meta["target_channel"] == target
            assert meta["input_channels"], "expected non-empty identity features"
            assert set(meta["input_channels"]).issubset(IDENTITY_CHANNELS), meta["input_channels"]
            assert meta["model_type"] in MODEL_TYPES, meta["model_type"]
            # Every selected model must provide an input-dependent std — never the
            # global residual std.
            assert meta["std_method"] in {"bayesian_posterior", "gaussian_posterior",
                                          "tree_variance"}, meta["std_method"]
            expected_dtype = "float64" if meta["model_type"] == "gaussian_process" else "float32"
            assert meta["onnx_input_dtype"] == expected_dtype, meta["onnx_input_dtype"]
            assert isinstance(meta["test_r2"], float)
            assert meta["atlas_version"]


def test_predict_with_std_rejects_non_input_dependent_models():
    """The std-method guard must reject any architecture without input-dependent std."""
    from smprofiler.atlas.models import predict_with_std

    for disallowed in ("ridge", "elastic_net", "huber", "xgboost"):
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
