#!/usr/bin/env python3
"""
Train atlas-reference regression models for SPT functional marker prediction.

For each (study, functional_marker) pair, trains a regression model on the
Allen Institute Human Immune Health Atlas that predicts functional marker
intensity from identity marker values. Models are exported to ONNX format.

Each model takes identity marker intensities as input (X) and predicts the
expected functional marker intensity (y) for a "normal" cell. At inference
time, cells whose measured intensity exceeds the prediction are flagged as
"atlas-relative positive" for that functional marker.

Usage:
    python scripts/train_atlas_models.py \\
        --atlas /path/to/human_immune_health_atlas_full.h5ad \\
        --annotations /path/to/annotations/channel_annotations.json \\
        --datasets-dir /path/to/datasets \\
        --output-dir models \\
        [--atlas-mapping channel_name_mapping.json] \\
        [--max-cells 500000] \\
        [--study luad_progression] \\
        [--cv-folds 5] \\
        [--dry-run]
"""

import argparse
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor
from sklearn.linear_model import ElasticNet, HuberRegressor, Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor
from onnxmltools import convert_xgboost
from onnxmltools.convert.common.data_types import FloatTensorType as XGBFloatTensorType
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
from onnxruntime import InferenceSession, SessionOptions
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# Suppress verbose output from the ONNX ecosystem
logging.getLogger("skl2onnx").setLevel(logging.WARNING)
logging.getLogger("onnx").setLevel(logging.WARNING)
logging.getLogger("onnxruntime").setLevel(logging.WARNING)


@contextlib.contextmanager
def _silence_fd():
    """Redirect OS-level stdout/stderr to /dev/null (suppresses C-ext prints)."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        os.close(devnull)

ATLAS_VERSION = "allen-human-immune-health-atlas-2025"

# Width of visual separator lines
_SEP_WIDTH = 70


def _section(title: str) -> None:
    """Print a prominent section header to stdout (bypasses log timestamps)."""
    bar = "═" * _SEP_WIDTH
    print(f"\n{bar}", flush=True)
    print(f"  {title}", flush=True)
    print(bar, flush=True)


def _subsection(title: str) -> None:
    """Print a lighter sub-section divider."""
    print(f"\n{'─' * _SEP_WIDTH}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'─' * _SEP_WIDTH}", flush=True)


def _fmt_elapsed(seconds: float) -> str:
    """Return a human-readable elapsed time string."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


# ---------------------------------------------------------------------------
# Channel annotation helpers
# ---------------------------------------------------------------------------

def load_channel_annotations(annotations_path: Path) -> tuple[set, set, dict]:
    """
    Parse channel_annotations.json.

    Returns:
        identity_channels: set of canonical identity channel names
        functional_channels: set of canonical functional channel names
        aliases: dict mapping alias → canonical name (for channels only)
    """
    with open(annotations_path) as f:
        data = json.load(f)

    groups = data["groups"]
    identity_channels: set = set(groups["identity"]["channels"])

    functional_channels: set = set()
    for group_name, group_data in groups.items():
        if group_name not in ("identity", "tumor"):
            functional_channels.update(group_data["channels"])

    all_channels = identity_channels | functional_channels

    # Filter aliases to channel aliases only (aliases also contains cell type strings)
    aliases = {}
    for alias, canonical in data.get("aliases", {}).items():
        if isinstance(canonical, str) and canonical in all_channels:
            aliases[alias] = canonical

    log.info(
        "Channel annotations: %d identity, %d functional, %d aliases",
        len(identity_channels), len(functional_channels), len(aliases),
    )
    return identity_channels, functional_channels, aliases


def normalize_name(name: str, aliases: dict) -> str:
    """Resolve a channel name to its canonical form via the aliases map."""
    return aliases.get(name, name)


# ---------------------------------------------------------------------------
# Per-study channel discovery
# ---------------------------------------------------------------------------

def _read_channel_names_from_file(path: Path, aliases: dict) -> list[str]:
    """
    Read channel names from an elementary_phenotypes or channels file.

    Handles:
    - CSV / TSV with 'Symbol' column  (elementary_phenotypes_overlay.csv)
    - CSV / TSV with 'Name' column    (elementary_phenotypes.csv, channels.tsv)
    """
    sep = "\t" if path.suffix == ".tsv" else ","
    try:
        df = pd.read_csv(path, sep=sep)
    except Exception as exc:
        log.warning("Could not read %s: %s", path, exc)
        return []

    col = None
    for candidate in ("Symbol", "Name"):
        if candidate in df.columns:
            col = candidate
            break

    if col is None:
        log.warning("No 'Symbol' or 'Name' column in %s (columns: %s)", path, list(df.columns))
        return []

    names = []
    for raw in df[col].dropna():
        canonical = normalize_name(str(raw).strip(), aliases)
        names.append(canonical)
    return names


def discover_study_channels(
    datasets_dir: Path,
    studies: list[str],
    identity_channels: set,
    functional_channels: set,
    aliases: dict,
) -> dict[str, dict]:
    """
    For each study, locate channel definition files and split into identity /
    functional lists based on the global channel annotation groups.

    Returns:
        dict mapping study_name → {
            "identity": [channel, ...],
            "functional": [channel, ...],
        }
    """
    # File name patterns to search, in priority order:
    # overlay files use 'Symbol' column; others use 'Name' column
    candidates_patterns = [
        "**/elementary_phenotypes_overlay*.csv",
        "**/elementary_phenotypes.csv",
        "**/channels.tsv",
    ]

    results = {}
    for study_name in studies:
        study_dir = datasets_dir / study_name
        if not study_dir.is_dir():
            log.warning("Dataset directory not found: %s", study_dir)
            continue

        all_names: list[str] = []
        for pattern in candidates_patterns:
            files = sorted(study_dir.glob(pattern))
            for f in files:
                names = _read_channel_names_from_file(f, aliases)
                all_names.extend(names)
            if all_names:
                break  # stop searching once we found something

        if not all_names:
            log.warning("No channel files found for study '%s' – skipping", study_name)
            continue

        # Deduplicate while preserving order
        seen: set = set()
        unique_names = []
        for n in all_names:
            if n not in seen:
                seen.add(n)
                unique_names.append(n)

        identity = [n for n in unique_names if n in identity_channels]
        functional = [n for n in unique_names if n in functional_channels]

        if not identity:
            log.warning("Study '%s': no identity channels found, skipping", study_name)
            continue
        if not functional:
            log.warning("Study '%s': no functional channels found, skipping", study_name)
            continue

        results[study_name] = {"identity": identity, "functional": functional}
        log.info(
            "Study '%s': %d identity channels, %d functional channels",
            study_name, len(identity), len(functional),
        )
        log.debug("  Identity:   %s", identity)
        log.debug("  Functional: %s", functional)

    return results


# ---------------------------------------------------------------------------
# Atlas loading
# ---------------------------------------------------------------------------

def load_atlas_var_names(atlas_path: Path) -> list[str]:
    """Return var_names from the atlas without loading the expression matrix."""
    size_gb = atlas_path.stat().st_size / 1024 ** 3
    log.info("Opening atlas (%.1f GB): %s", size_gb, atlas_path)
    t0 = time.monotonic()
    adata = ad.read_h5ad(atlas_path, backed="r")
    var_names = list(adata.var_names)
    n_obs = adata.n_obs
    adata.file.close()
    log.info(
        "Atlas index loaded in %s — %s cells × %d markers",
        _fmt_elapsed(time.monotonic() - t0), f"{n_obs:,}", len(var_names),
    )
    return var_names


def build_atlas_channel_map(
    atlas_var_names: list[str],
    spt_channels: set,
    aliases: dict,
    extra_mapping: dict | None = None,
) -> dict[str, str]:
    """
    Build a mapping: atlas_var_name → canonical SPT channel name.

    Resolution order:
    1. Extra manual mapping (channel_name_mapping.json)
    2. Alias lookup (e.g. atlas has 'CD8A', SPT has 'CD8' via alias CD8A→CD8)
    3. Exact case-insensitive match

    Returns dict of {atlas_var_name: spt_canonical_name} for matched entries only.
    """
    extra = extra_mapping or {}
    # Build reverse alias map: canonical → [aliases...]  (not needed directly)
    # Build lookup from atlas name → SPT canonical
    atlas_upper_to_name = {n.upper(): n for n in atlas_var_names}

    spt_channels_upper = {c.upper(): c for c in spt_channels}

    atlas_to_spt: dict[str, str] = {}
    for atlas_name in atlas_var_names:
        # 1. Manual mapping
        if atlas_name in extra:
            canonical = extra[atlas_name]
            if canonical in spt_channels:
                atlas_to_spt[atlas_name] = canonical
                continue

        # 2. The atlas name itself might be an alias
        canonical = normalize_name(atlas_name, aliases)
        if canonical in spt_channels:
            atlas_to_spt[atlas_name] = canonical
            continue

        # 3. Case-insensitive exact match
        upper = atlas_name.upper()
        if upper in spt_channels_upper:
            atlas_to_spt[atlas_name] = spt_channels_upper[upper]
            continue

    # Reverse: which SPT channels have no atlas match?
    matched_spt = set(atlas_to_spt.values())
    unmatched = spt_channels - matched_spt
    if unmatched:
        log.warning("SPT channels with NO atlas match: %s", sorted(unmatched))

    log.info(
        "Atlas ↔ SPT mapping: %d matched (out of %d SPT channels)",
        len(matched_spt), len(spt_channels),
    )
    return atlas_to_spt


def load_atlas_subset(
    atlas_path: Path,
    atlas_columns: list[str],
    spt_names: list[str],
    max_cells: Optional[int] = None,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, list[str]]:
    """
    Load specific columns from the atlas h5ad file into memory.

    Args:
        atlas_path: path to the h5ad file
        atlas_columns: atlas var_names to load (must exist in the file)
        spt_names: corresponding SPT canonical names (same length as atlas_columns)
        max_cells: if set, randomly sample this many cells
        rng: random number generator for sampling

    Returns:
        (X, spt_names_present) where X has shape (n_cells, len(atlas_columns))
    """
    log.info("Loading %d atlas columns: %s", len(atlas_columns), atlas_columns)
    t0 = time.monotonic()
    adata = ad.read_h5ad(atlas_path, backed="r")
    n_total = adata.n_obs

    # Determine row indices to load
    if max_cells and n_total > max_cells:
        if rng is None:
            rng = np.random.default_rng(42)
        idx = rng.choice(n_total, size=max_cells, replace=False)
        idx.sort()
        log.info(
            "Sampling %s / %s cells from atlas (%.1f%%)…",
            f"{max_cells:,}", f"{n_total:,}", 100 * max_cells / n_total,
        )
    else:
        idx = slice(None)
        log.info("Loading all %s cells from atlas…", f"{n_total:,}")

    subset = adata[idx, atlas_columns]
    X = subset.X
    if sparse.issparse(X):
        X = X.toarray()
    else:
        X = np.asarray(X)

    adata.file.close()

    X = X.astype(np.float32)
    log.info(
        "Atlas data loaded in %s — shape %s (%.1f MB)",
        _fmt_elapsed(time.monotonic() - t0),
        X.shape,
        X.nbytes / 1024 ** 2,
    )
    return X, spt_names


# ---------------------------------------------------------------------------
# Model definitions
# ---------------------------------------------------------------------------

def build_model_candidates() -> list[tuple[str, object]]:
    """Return list of (name, sklearn_estimator) for all candidate models."""
    return [
        (
            "extra_trees",
            ExtraTreesRegressor(
                n_estimators=100,
                max_depth=8,
                n_jobs=-1,
                random_state=42,
            ),
        ),
        (
            "random_forest",
            RandomForestRegressor(
                n_estimators=100,
                max_depth=8,
                n_jobs=-1,
                random_state=42,
            ),
        ),
        (
            "ridge",
            Pipeline([
                ("scaler", StandardScaler()),
                ("ridge", Ridge(alpha=1.0)),
            ]),
        ),
        (
            "elastic_net",
            Pipeline([
                ("scaler", StandardScaler()),
                ("enet", ElasticNet(alpha=0.01, l1_ratio=0.5, max_iter=2000)),
            ]),
        ),
        (
            "huber",
            Pipeline([
                ("scaler", StandardScaler()),
                ("huber", HuberRegressor(epsilon=1.35, max_iter=200)),
            ]),
        ),
        (
            "xgboost",
            XGBRegressor(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                tree_method="hist",
                n_jobs=-1,
                random_state=42,
                verbosity=0,
            ),
        ),
    ]


def train_and_select_best(
    X_train: np.ndarray,
    y_train: np.ndarray,
    cv_folds: int = 5,
) -> tuple[str, object, float, float]:
    """
    Train all candidate models with k-fold CV, select the one with highest R².

    Returns:
        (best_model_name, fitted_best_model, cv_r2_mean, cv_r2_std)
    """
    candidates = build_model_candidates()
    best_name = None
    best_model = None
    best_r2 = -np.inf
    best_std = np.nan

    for name, model in tqdm(candidates, desc="  CV candidates", leave=False,
                            bar_format="  {desc}: {n_fmt}/{total_fmt} [{bar}] {postfix}"):
        t0 = time.monotonic()
        scores = cross_val_score(
            model, X_train, y_train,
            cv=cv_folds, scoring="r2", n_jobs=-1,
        )
        mean_r2 = float(scores.mean())
        std_r2 = float(scores.std())
        elapsed = _fmt_elapsed(time.monotonic() - t0)
        marker = " ★" if mean_r2 > best_r2 else ""
        log.info("    %-28s R²=%+.4f ± %.4f  [%s]%s",
                 name, mean_r2, std_r2, elapsed, marker)

        if mean_r2 > best_r2:
            best_r2 = mean_r2
            best_std = std_r2
            best_name = name
            best_model = model

    # Refit best model on full training set
    log.info("  → Refitting winner '%s' on full train set…", best_name)
    t0 = time.monotonic()
    best_model.fit(X_train, y_train)
    log.info("  → Done in %s  (CV R²=%.4f ± %.4f)",
             _fmt_elapsed(time.monotonic() - t0), best_r2, best_std)
    return best_name, best_model, best_r2, best_std


# ---------------------------------------------------------------------------
# ONNX export and validation
# ---------------------------------------------------------------------------

def export_to_onnx(model, n_features: int, output_path: Path) -> None:
    """Convert a fitted sklearn estimator / pipeline to ONNX and save."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _silence_fd():
        if isinstance(model, XGBRegressor):
            initial_type = [("X", XGBFloatTensorType([None, n_features]))]
            onnx_model = convert_xgboost(model, initial_types=initial_type)
        else:
            initial_type = [("X", FloatTensorType([None, n_features]))]
            onnx_model = convert_sklearn(model, initial_types=initial_type)
    with open(output_path, "wb") as f:
        f.write(onnx_model.SerializeToString())
    size_kb = output_path.stat().st_size / 1024
    log.info("ONNX model saved: %s (%.1f KB)", output_path, size_kb)


def validate_onnx(onnx_path: Path, sklearn_model, X_sample: np.ndarray) -> bool:
    """
    Run the ONNX model and compare output to sklearn's predictions.
    Returns True if outputs match within tolerance.
    """
    _ort_opts = SessionOptions()
    _ort_opts.log_severity_level = 3  # 0=VERBOSE … 3=ERROR
    with _silence_fd():
        sess = InferenceSession(str(onnx_path), sess_options=_ort_opts)
    X_f32 = X_sample.astype(np.float32)
    onnx_pred = sess.run(None, {"X": X_f32})[0].flatten()
    sklearn_pred = sklearn_model.predict(X_sample)
    max_diff = np.abs(onnx_pred - sklearn_pred).max()
    if max_diff > 1e-3:
        log.warning("ONNX validation: max abs diff = %.6f (tolerated up to 1e-3)", max_diff)
        return False
    log.info("ONNX validation passed (max abs diff = %.2e)", max_diff)
    return True


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def write_metadata(
    output_path: Path,
    study: str,
    target_channel: str,
    input_channels: list[str],
    model_type: str,
    cv_r2: float,
    cv_r2_std: float,
    test_r2: float,
    test_mae: float,
    n_train: int,
    n_test: int,
    atlas_version: str,
) -> None:
    meta = {
        "study": study,
        "target_channel": target_channel,
        "input_channels": input_channels,
        "model_type": model_type,
        "cv_r2": round(cv_r2, 6),
        "cv_r2_std": round(cv_r2_std, 6),
        "test_r2": round(test_r2, 6),
        "test_mae": round(test_mae, 6),
        "n_train": n_train,
        "n_test": n_test,
        "atlas_version": atlas_version,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(meta, f, indent=2)
    log.info("Metadata saved: %s", output_path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    atlas_path = Path(args.atlas)
    annotations_path = Path(args.annotations)
    datasets_dir = Path(args.datasets_dir)
    output_dir = Path(args.output_dir)

    if not atlas_path.exists():
        log.error("Atlas file not found: %s", atlas_path)
        sys.exit(1)
    if not annotations_path.exists():
        log.error("Annotations file not found: %s", annotations_path)
        sys.exit(1)

    # Load extra atlas→SPT name mapping if provided
    extra_mapping: dict = {}
    if args.atlas_mapping and Path(args.atlas_mapping).exists():
        with open(args.atlas_mapping) as f:
            extra_mapping = json.load(f)
        log.info("Loaded %d entries from extra atlas mapping", len(extra_mapping))

    # Step 1: Load channel annotations
    identity_channels, functional_channels, aliases = load_channel_annotations(annotations_path)
    all_channels = identity_channels | functional_channels

    # Step 2: Discover per-study channel lists
    if args.study:
        study_list = [args.study]
    else:
        study_list = [
            d.name for d in sorted(datasets_dir.iterdir())
            if d.is_dir() and d.name != "template"
        ]

    study_channels = discover_study_channels(
        datasets_dir, study_list, identity_channels, functional_channels, aliases
    )

    if not study_channels:
        log.error("No studies with channel data found. Exiting.")
        sys.exit(1)

    # Step 3: Load atlas var_names (backed, fast)
    atlas_var_names = load_atlas_var_names(atlas_path)

    # Step 4: Build atlas ↔ SPT mapping
    atlas_to_spt = build_atlas_channel_map(
        atlas_var_names, all_channels, aliases, extra_mapping
    )
    # Reverse map: SPT canonical → atlas var_name
    spt_to_atlas = {spt: atl for atl, spt in atlas_to_spt.items()}

    # ── Compute training plan up-front ──────────────────────────────────────
    plan: list[dict] = []
    for study_name, channels in study_channels.items():
        id_in_atlas = [c for c in channels["identity"] if c in spt_to_atlas]
        fn_in_atlas = [c for c in channels["functional"] if c in spt_to_atlas]
        if id_in_atlas and fn_in_atlas:
            plan.append({
                "study": study_name,
                "identity": id_in_atlas,
                "functional": fn_in_atlas,
            })

    total_models = sum(len(p["functional"]) for p in plan)

    if args.dry_run:
        _section("DRY RUN — Training plan")
        for p in plan:
            _subsection(f"Study: {p['study']}")
            log.info(
                "  Identity features (%d): %s", len(p["identity"]), p["identity"]
            )
            for fc in p["functional"]:
                log.info("  → model: target='%s'  features=%s", fc, p["identity"])
        print(f"\nTotal: {len(plan)} studies, {total_models} models to train.", flush=True)
        return

    _section(
        f"Atlas-reference model training — "
        f"{len(plan)} studies, {total_models} models total"
    )
    log.info("Output directory: %s", output_dir.resolve())
    if args.max_cells:
        log.info("Max atlas cells per study: %s", f"{args.max_cells:,}")
    else:
        log.info("Using full atlas (no cell limit)")
    log.info("Cross-validation folds: %d", args.cv_folds)

    rng = np.random.default_rng(42)
    run_start = time.monotonic()
    model_counter = 0
    summary_rows: list[dict] = []

    # Step 5: For each study × functional_marker pair, train a model
    for study_idx, p in enumerate(plan, 1):
        study_name = p["study"]
        id_in_atlas = p["identity"]
        fn_in_atlas = p["functional"]

        _section(
            f"[{study_idx}/{len(plan)}] Study: {study_name}  "
            f"({len(fn_in_atlas)} models to train)"
        )
        log.info("  Identity features : %s", id_in_atlas)
        log.info("  Functional targets: %s", fn_in_atlas)

        # Load all needed atlas columns in one shot (identity + all functional targets)
        needed_spt = id_in_atlas + [f for f in fn_in_atlas if f not in id_in_atlas]
        needed_atlas = [spt_to_atlas[c] for c in needed_spt]

        study_load_start = time.monotonic()
        X_all, _ = load_atlas_subset(
            atlas_path, needed_atlas, needed_spt,
            max_cells=args.max_cells, rng=rng,
        )

        # Build column index lookup
        col_idx = {name: i for i, name in enumerate(needed_spt)}
        X_identity = X_all[:, [col_idx[c] for c in id_in_atlas]]

        for target_idx_local, target_channel in enumerate(fn_in_atlas, 1):
            model_counter += 1
            _subsection(
                f"Model [{model_counter}/{total_models}]  "
                f"study='{study_name}'  target='{target_channel}'  "
                f"({target_idx_local}/{len(fn_in_atlas)} in study)"
            )

            target_col = col_idx[target_channel]
            y = X_all[:, target_col]

            # Skip if target has zero variance (uninformative)
            if y.std() < 1e-6:
                log.warning("Skipping: target '%s' has near-zero variance", target_channel)
                continue

            log.info("  Features : %d identity markers, %s train cells",
                     X_identity.shape[1], f"{int(X_identity.shape[0] * 0.8):,}")
            log.info("  Target   : '%s'  (range %.3f – %.3f, mean %.3f)",
                     target_channel, float(y.min()), float(y.max()), float(y.mean()))

            # Train/test split
            X_train, X_test, y_train, y_test = train_test_split(
                X_identity, y, test_size=0.2, random_state=42
            )
            log.info("  Split    : %s train / %s test",
                     f"{len(X_train):,}", f"{len(X_test):,}")

            # Train all candidates, select best by CV R²
            log.info("  Training %d model candidates with %d-fold CV …",
                     len(build_model_candidates()), args.cv_folds)
            t_train_start = time.monotonic()
            best_name, best_model, cv_r2, cv_r2_std = train_and_select_best(
                X_train, y_train, cv_folds=args.cv_folds
            )

            # Evaluate on held-out test set
            y_pred = best_model.predict(X_test)
            test_r2 = float(r2_score(y_test, y_pred))
            test_mae = float(mean_absolute_error(y_test, y_pred))
            train_elapsed = _fmt_elapsed(time.monotonic() - t_train_start)
            log.info(
                "  Result   : model='%s'  test_R²=%.4f  test_MAE=%.4f  [%s]",
                best_name, test_r2, test_mae, train_elapsed,
            )

            # Sanitize channel name for filesystem
            safe_target = target_channel.replace("/", "_").replace(" ", "_")
            study_out_dir = output_dir / study_name
            onnx_path = study_out_dir / f"{safe_target}.onnx"
            meta_path = study_out_dir / f"{safe_target}.meta.json"

            # Export to ONNX
            export_to_onnx(best_model, X_identity.shape[1], onnx_path)

            # Validate ONNX output matches sklearn
            n_validate = min(500, X_test.shape[0])
            validate_onnx(onnx_path, best_model, X_test[:n_validate])

            # Write metadata
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
            )

            summary_rows.append({
                "study": study_name,
                "target": target_channel,
                "model": best_name,
                "cv_R²": cv_r2,
                "test_R²": test_r2,
                "test_MAE": test_mae,
                "onnx_kb": onnx_path.stat().st_size // 1024,
            })

    # ── Final summary ────────────────────────────────────────────────────────
    total_elapsed = _fmt_elapsed(time.monotonic() - run_start)
    _section(f"Training complete — {model_counter} models in {total_elapsed}")
    if summary_rows:
        col_widths = {"study": 24, "target": 16, "model": 24,
                      "cv_R²": 8, "test_R²": 8, "test_MAE": 10, "onnx_kb": 8}
        header = (f"  {'Study':<24}  {'Target':<16}  {'Model':<24}"
                  f"  {'cv_R²':>8}  {'test_R²':>8}  {'test_MAE':>10}  {'KB':>6}")
        print(header, flush=True)
        print("  " + "─" * (_SEP_WIDTH - 2), flush=True)
        for row in summary_rows:
            print(
                f"  {row['study']:<24}  {row['target']:<16}  {row['model']:<24}"
                f"  {row['cv_R²']:>8.4f}  {row['test_R²']:>8.4f}"
                f"  {row['test_MAE']:>10.4f}  {row['onnx_kb']:>6}",
                flush=True,
            )
    print(f"\nModels saved to: {output_dir.resolve()}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    _data_dir = Path(__file__).resolve().parent.parent.parent / "smprofiler-data"

    parser = argparse.ArgumentParser(
        description="Train atlas-reference regression models for SPT",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--atlas",
        default=str(_data_dir / "human_immune_health_atlas_full.h5ad"),
        help="Path to the Allen Institute Human Immune Health Atlas h5ad file",
    )
    parser.add_argument(
        "--annotations",
        default=str(_data_dir / "annotations" / "channel_annotations.json"),
        help="Path to channel_annotations.json",
    )
    parser.add_argument(
        "--datasets-dir",
        default=str(_data_dir / "datasets"),
        help="Root directory containing per-study dataset folders",
    )
    parser.add_argument(
        "--output-dir",
        default="models",
        help="Output directory for ONNX models and metadata",
    )
    parser.add_argument(
        "--atlas-mapping",
        default=None,
        help="Optional JSON file with extra atlas_var_name → spt_channel_name mappings",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=None,
        help="Max number of atlas cells to use (random sample). None = use all",
    )
    parser.add_argument(
        "--study",
        default=None,
        help="Train only for this study (default: all discovered studies)",
    )
    parser.add_argument(
        "--cv-folds",
        type=int,
        default=5,
        help="Number of cross-validation folds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the training plan without actually training any models",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    run(args)
