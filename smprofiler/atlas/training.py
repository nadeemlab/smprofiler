"""Atlas-reference model training pipeline.

Orchestrates the end-to-end run:
- Load channel annotations
- Determine available per-study identity/functional channels
- Map SMProfiler channels onto atlas genes (via the manually-maintained mapping)
- Read the aggregated atlas expression table (Parquet)
- Train and export one regression model per (study, functional_marker) and reference dataset

The command line adapter for ``run`` lives in ``smprofiler.atlas.scripts.train_atlas_models``.
"""
import pickle
import time
from pathlib import Path
from json import read as json_read

import numpy as np
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from smprofiler.standalone_utilities.log_formats import colorized_logger
from smprofiler.db.study_tokens import StudyCollectionNaming
from smprofiler.atlas.reporting import format_elapsed, section, subsection
from smprofiler.atlas.channel_annotations import load_channel_annotations_from_api
from smprofiler.atlas.study_channels import retrieve_all_study_channels_from_api
from smprofiler.atlas.atlas_data import load_atlas_gene_names
from smprofiler.atlas.atlas_data import load_atlas_subset
from smprofiler.atlas.atlas_data import load_channel_mapping
from smprofiler.atlas.models import STD_METHODS
from smprofiler.atlas.models import build_model_candidates
from smprofiler.atlas.models import predict_with_std
from smprofiler.atlas.models import train_and_select_best
from smprofiler.atlas.artifacts import export_to_onnx, validate_onnx, write_metadata

logger = colorized_logger(__name__)

ATLAS_VERSION = 'allen-human-immune-health-atlas-2025'
DEFAULT_ANNOTATIONS_API_URL = 'https://smprofiler.io/api'
_SUMMARY_WIDTH = 70

def _store_models_in_db(database_config_file: Path, model_records: list[dict]) -> None:
    # Imported lazily so the file-only training path carries no database dependency.
    from smprofiler.db.accessors.atlas_models import store_models_in_db
    store_models_in_db(database_config_file, model_records) 


def run(
    parquet_atlas_path: Path,
    mapping_path: Path,
    datasets_dir: Path,
    output_dir: Path,
    *,
    annotations_api_url: str = DEFAULT_ANNOTATIONS_API_URL,
    max_cells: int | None = None,
    study: str | None = None,
    cv_folds: int = 5,
    dry_run: bool = False,
    database_config_file: Path | None = None,
) -> None:
    """
    Train atlas-reference regression models.

    Args:
        parquet_atlas_path: path to the aggregated atlas expression table
            (file cell_atlas_small.parquet) is cells × atlas genes.
        mapping_path: path to the manual SMProfiler-channel → atlas-gene mapping
            (smprofiler_channels_to_atlas.tsv).
        datasets_dir: root directory containing per-study dataset folders.
        output_dir: directory for ONNX models, pickles, and metadata.
        annotations_api_url: smprofiler API base URL - the source of channel
            annotations.
        max_cells: max atlas cells to use (random sample); None uses all cells.
        study: train only for this study; None discovers all studies.
        cv_folds: number of cross-validation folds.
        dry_run: print the training plan without training any models.
        database_config_file: if given, also store each trained model (ONNX model
        file + metadata) in the ``atlas_model`` table; None writes files only.

    Raises:
        FileNotFoundError
        RuntimeError if annotations cannot be loaded from the API, or if no
            studies with usable channel data are found.
    """
    if not parquet_atlas_path.exists():
        raise FileNotFoundError(f'Atlas parquet file not found: {parquet_atlas_path}')
    if not mapping_path.exists():
        raise FileNotFoundError(f'Channel mapping file not found: {mapping_path}')

    if not annotations_api_url:
        raise RuntimeError(
            'An annotations API URL is required — loading channel annotations from '
            'a local file is deprecated. Set annotations_api_url.'
        )
    try:
        identity_channels, aliases = load_channel_annotations_from_api(
            annotations_api_url
        )
    except Exception as exc:
        raise RuntimeError(
            f'Failed to load channel annotations from API {annotations_api_url}: {exc}'
        ) from exc

    if study:
        study_handles = [study]
    else:
        study_handles = [
            d.name for d in sorted(datasets_dir.iterdir())
            if d.is_dir() and d.name != 'template'
        ]

    _study_names = []
    for handle in study_handles:
        study_json = datasets_dir / handle / 'generated_artifacts' / 'study.json'
        if not study_json.exists():
            logger.warning("Dataset metadata not found for: %s", handle)
            continue
        _study_names.append(StudyCollectionNaming.extract_study_from_file(study_json))
    study_names = tuple(_study_names)

    study_channels = retrieve_all_study_channels_from_api(
        study_names, identity_channels, aliases, base_url=annotations_api_url
    )

    # Keep only mapped channels whose atlas gene is actually present in the Parquet table.
    spt_to_atlas = load_channel_mapping(mapping_path)
    atlas_genes = set(load_atlas_gene_names(parquet_atlas_path))
    absent = {spt: gene for spt, gene in spt_to_atlas.items() if gene not in atlas_genes}
    if absent:
        logger.warning(
            '%d mapped channels dropped — atlas gene absent from parquet: %s',
            len(absent), sorted(absent.items()),
        )
        spt_to_atlas = {spt: gene for spt, gene in spt_to_atlas.items() if gene in atlas_genes}
    logger.info(
        'Atlas feature summary: %d atlas genes in parquet, %d SPT channels mapped',
        len(atlas_genes), len(spt_to_atlas),
    )

    # ── Compute training plan up-front ──────────────────────────────────────
    plan: list[dict] = []
    for study_name, channels in study_channels.items():
        id_in_atlas = [c for c in channels['identity'] if c in spt_to_atlas]
        fn_in_atlas = [c for c in channels['functional'] if c in spt_to_atlas]
        logger.info(
            'Study "%s": %d dataset channels → %d atlas-matched '
            '(identity %d/%d, functional %d/%d)',
            study_name,
            len(channels['identity']) + len(channels['functional']),
            len(id_in_atlas) + len(fn_in_atlas),
            len(id_in_atlas), len(channels['identity']),
            len(fn_in_atlas), len(channels['functional']),
        )
        if id_in_atlas and fn_in_atlas:
            plan.append({
                'study': study_name,
                'identity': id_in_atlas,
                'functional': fn_in_atlas,
            })

    total_models = sum(len(p['functional']) for p in plan)

    if dry_run:
        section('DRY RUN — Training plan')
        for p in plan:
            subsection(f'Study: {p["study"]}')
            logger.info(
                '  Identity features (%d): %s', len(p['identity']), p['identity']
            )
            for fc in p['functional']:
                logger.info('  → model: target="%s"  features=%s', fc, p['identity'])
        print(f'\nTotal: {len(plan)} studies, {total_models} models to train.', flush=True)
        return

    section(
        f'Atlas-reference model training — '
        f'{len(plan)} studies, {total_models} models total'
    )
    logger.info('Output directory: %s', output_dir.resolve())
    if max_cells:
        logger.info('Max atlas cells per study: %s', f'{max_cells:,}')
    else:
        logger.info('Using full atlas (no cell limit)')
    logger.info('Cross-validation folds: %d', cv_folds)

    rng = np.random.default_rng(42)
    run_start = time.monotonic()
    model_counter = 0
    summary_rows: list[dict] = []
    model_records: list[dict] = []  # collected for optional database storage

    # Train one model per (study, functional marker).
    for study_idx, p in enumerate(plan, 1):
        study_name = p['study']
        id_in_atlas = p['identity']
        fn_in_atlas = p['functional']

        section(
            f'[{study_idx}/{len(plan)}] Study: {study_name}  '
            f'({len(fn_in_atlas)} models to train)'
        )
        logger.info('  Identity features : %s', id_in_atlas)
        logger.info('  Functional targets: %s', fn_in_atlas)

        # Load all needed atlas columns in one shot (identity + all functional targets)
        needed_spt = id_in_atlas + [f for f in fn_in_atlas if f not in id_in_atlas]
        needed_atlas = [spt_to_atlas[c] for c in needed_spt]

        X_all, _ = load_atlas_subset(
            parquet_atlas_path, needed_atlas, needed_spt,
            max_cells=max_cells, rng=rng,
        )

        col_idx = {name: i for i, name in enumerate(needed_spt)}
        X_identity = X_all[:, [col_idx[c] for c in id_in_atlas]]

        # Sum-normalize by identity-channel row sums (removes overall scale effect).
        row_sums = X_identity.sum(axis=1)
        valid_mask = row_sums > 1e-8
        n_zero_sum = int((~valid_mask).sum())
        if n_zero_sum:
            logger.info('  Removed %d cells with zero identity-channel sum', n_zero_sum)
        X_identity_norm = X_identity[valid_mask] / row_sums[valid_mask, np.newaxis]
        X_all_filtered = X_all[valid_mask]
        S_valid = row_sums[valid_mask]
        logger.info(
            '  Normalized: %s cells retained  (%.2f%% of loaded)',
            f'{X_identity_norm.shape[0]:,}',
            100.0 * X_identity_norm.shape[0] / X_all.shape[0],
        )

        for target_idx_local, target_channel in enumerate(fn_in_atlas, 1):
            model_counter += 1
            subsection(
                f'Model [{model_counter}/{total_models}]  '
                f'study="{study_name}"  target="{target_channel}"  '
                f'({target_idx_local}/{len(fn_in_atlas)} in study)'
            )

            target_col = col_idx[target_channel]
            y_norm = X_all_filtered[:, target_col] / S_valid

            # Skip if target has zero variance after normalization (uninformative)
            if y_norm.std() < 1e-6:
                logger.warning("Skipping: target '%s' has near-zero variance", target_channel)
                continue

            logger.info('  Features : %d identity markers, %s cells (after S>0 filter)',
                        X_identity_norm.shape[1], f'{X_identity_norm.shape[0]:,}')
            logger.info('  Target   : "%s" (norm; range %.4f – %.4f, mean %.4f)',
                        target_channel, float(y_norm.min()), float(y_norm.max()), float(y_norm.mean()))

            X_train, X_test, y_train, y_test = train_test_split(
                X_identity_norm, y_norm, test_size=0.2, random_state=42
            )
            logger.info('  Split    : %s train / %s test',
                        f'{len(X_train):,}', f'{len(X_test):,}')

            logger.info('  Training %d model candidates with %d-fold CV …',
                        len(build_model_candidates()), cv_folds)
            t_train_start = time.monotonic()
            best_name, best_model, cv_r2, cv_r2_std = train_and_select_best(
                X_train, y_train, cv_folds=cv_folds
            )

            y_pred_mean, y_pred_std = predict_with_std(best_model, best_name, X_test)
            test_r2 = float(r2_score(y_test, y_pred_mean))
            test_mae = float(mean_absolute_error(y_test, y_pred_mean))
            residuals = y_test - y_pred_mean
            global_std = float(residuals.std())
            std_method = STD_METHODS[best_name]
            # GaussianProcess only reproduces in double precision; others use float32.
            double_precision = best_name == 'gaussian_process'
            onnx_input_dtype = 'float64' if double_precision else 'float32'
            train_seconds = time.monotonic() - t_train_start
            train_elapsed = format_elapsed(train_seconds)
            logger.info(
                '  Result   : model="%s"  test_R²=%.4f  test_MAE=%.4f'
                '  std_method=%s  global_std=%.4f  [%s]',
                best_name, test_r2, test_mae, std_method, global_std, train_elapsed,
            )

            # Sanitize channel name for filesystem
            safe_target = target_channel.replace('/', '_').replace(' ', '_')
            study_out_dir = output_dir / study_name
            onnx_path = study_out_dir / f'{safe_target}.onnx'
            pkl_path = study_out_dir / f'{safe_target}.pkl'
            meta_path = study_out_dir / f'{safe_target}.meta.json'

            export_to_onnx(best_model, X_identity_norm.shape[1], onnx_path,
                           double_precision=double_precision)

            n_validate = min(500, X_test.shape[0])
            validate_onnx(onnx_path, best_model, X_test[:n_validate],
                          double_precision=double_precision)

            # Keep the sklearn pickle too: per-cell std is computed in Python, not from ONNX.
            study_out_dir.mkdir(parents=True, exist_ok=True)
            with open(pkl_path, 'wb') as pkl_f:
                pickle.dump(best_model, pkl_f)
            logger.info('Pickle saved: %s (%.1f KB)', pkl_path, pkl_path.stat().st_size / 1024)

            write_metadata(
                meta_path,
                study=study_name,
                target_channel=target_channel,
                input_channels=id_in_atlas,
                model_type=best_name,
                cv_r2=cv_r2,
                cv_r2_std=cv_r2_std,
                test_r2=test_r2,
                test_mae=test_mae,
                n_train=len(X_train),
                n_test=len(X_test),
                atlas_version=ATLAS_VERSION,
                sum_normalized=True,
                std_method=std_method,
                global_std=global_std,
                onnx_input_dtype=onnx_input_dtype,
            )

            summary_rows.append({
                'study': study_name,
                'target': target_channel,
                'model': best_name,
                'std_method': std_method,
                'cv_R²': cv_r2,
                'test_R²': test_r2,
                'test_MAE': test_mae,
                'onnx_kb': onnx_path.stat().st_size // 1024,
            })

            if database_config_file is not None:
                model_records.append({
                    'study': study_name,
                    'target_channel': target_channel,
                    'input_channels': id_in_atlas,
                    'architecture_type': best_name,
                    'std_method': std_method,
                    'onnx_input_dtype': onnx_input_dtype,
                    'atlas_version': ATLAS_VERSION,
                    'cv_r2': cv_r2,
                    'test_r2': test_r2,
                    'test_mae': test_mae,
                    'n_train': len(X_train),
                    'n_test': len(X_test),
                    'training_time_seconds': train_seconds,
                    'onnx_bytes': onnx_path.read_bytes(),
                })

    if model_records:
        _store_models_in_db(database_config_file, model_records)

    # ── Final summary ────────────────────────────────────────────────────────
    total_elapsed = format_elapsed(time.monotonic() - run_start)
    section(f'Training complete — {model_counter} models in {total_elapsed}')
    if summary_rows:
        header = (f'  {"Study":<24}  {"Target":<16}  {"Model":<24}  {"Std method":<22}'
                  f'  {"cv_R²":>8}  {"test_R²":>8}  {"test_MAE":>10}  {"KB":>6}')
        print(header, flush=True)
        print('  ' + '─' * (_SUMMARY_WIDTH - 2), flush=True)
        for row in summary_rows:
            print(
                f'  {row["study"]:<24}  {row["target"]:<16}  {row["model"]:<24}'
                f'  {row["std_method"]:<22}'
                f'  {row["cv_R²"]:>8.4f}  {row["test_R²"]:>8.4f}'
                f'  {row["test_MAE"]:>10.4f}  {row["onnx_kb"]:>6}',
                flush=True,
            )
    print(f'\nModels saved to: {output_dir.resolve()}', flush=True)

