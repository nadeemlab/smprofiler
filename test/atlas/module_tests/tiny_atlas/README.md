# Tiny atlas fixture

A minimal, self-contained test dataset. It lets the training pipeline run
end-to-end without the 42 GB atlas download.

## Contents
- `cell_atlas_small.parquet` - 3000 cells by 12 genes of **real** expression values
  sampled from `human_immune_health_atlas_full.h5ad` (~1200 cells survive the
  identity-sum filter). Shaped like the aggregation step's output.

