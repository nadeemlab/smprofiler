# Tiny atlas fixture

A minimal, self-contained fixture for `../test_train_atlas_models.py`. It lets the
training pipeline run end-to-end without the 42 GB atlas download.

## Contents
- `cell_atlas_small.parquet` — 3000 cells × 12 genes of **real** expression values
  sampled from `human_immune_health_atlas_full.h5ad` (~1200 cells survive the
  identity-sum filter). Shaped like the aggregation step's output.
- `smprofiler_channels_to_atlas.tsv` — SMProfiler channel → atlas gene mapping (12 channels).
- `datasets/test_study/generated_artifacts/study.json` — names the one study (`test_study`);
  `elementary_phenotypes.csv` lists its 12 channels.

Channel annotations (identity: 7 lineage markers; functional: 5 state markers), study
availability and per-study channel order are normally fetched from the smprofiler API;
the test stubs all three calls, deriving the study channels from the TSV. The
classification is chosen for the test; only the expression values are from the real atlas.

## Regenerating
Sampled with seed 0 from the atlas file (a sibling `smprofiler-data/`), selecting the
genes CD8A, MS4A1, PECAM1, CD68, CD14, CD19, NCAM1 (identity) and FOXP3, MKI67, GZMB,
PDCD1, HAVCR2 (functional). See the commit that introduced this directory for the
one-off extraction script.
