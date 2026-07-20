"""Store and retrieve trained atlas-reference models in the ``atlas_model`` table.

The table lives in the shared metaschema, so use a metaschema cursor
(``DBCursor(database_config_file=...)`` with no ``study``). Each stored row is a
versioned snapshot: multiple rows may share a (study, target_channel), ordered by
``created``.
"""
from pathlib import Path

from psycopg import Cursor as PsycopgCursor

from smprofiler.db.database_connection import DBCursor
from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)

# Metadata columns returned by list_atlas_models (everything except the ONNX bytes).
_METADATA_COLUMNS = (
    "id", "study", "target_channel", "input_channels", "architecture_type",
    "std_method", "onnx_input_dtype", "atlas_version", "cv_r2", "test_r2",
    "test_mae", "n_train", "n_test", "training_time_seconds", "size_bytes", "created",
)

_INSERT = """
INSERT INTO atlas_model (
    study, target_channel, input_channels, architecture_type, std_method,
    onnx_input_dtype, atlas_version, cv_r2, test_r2, test_mae, n_train, n_test,
    training_time_seconds, size_bytes, onnx_model
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id ;
"""

def store_models_in_db(database_config_file: Path, model_records: list[dict]) -> None:
    """Persist trained models to the ``atlas_model`` table."""
    logger.info('Storing %d trained model(s) to the "atlas_model" database table…', len(model_records))
    with DBCursor(database_config_file=str(database_config_file)) as cursor:
        for record in model_records:
            store_atlas_model(cursor, **record)

def store_atlas_model(
    cursor: PsycopgCursor,
    *,
    study: str,
    target_channel: str,
    input_channels: list[str],
    architecture_type: str,
    std_method: str,
    onnx_input_dtype: str,
    onnx_bytes: bytes,
    atlas_version: str | None = None,
    cv_r2: float | None = None,
    test_r2: float | None = None,
    test_mae: float | None = None,
    n_train: int | None = None,
    n_test: int | None = None,
    training_time_seconds: float | None = None,
) -> int:
    """Insert one trained model (ONNX bytes + metadata) and return its new id."""
    size_bytes = len(onnx_bytes)
    cursor.execute(_INSERT, (
        study, target_channel, list(input_channels), architecture_type, std_method,
        onnx_input_dtype, atlas_version, cv_r2, test_r2, test_mae, n_train, n_test,
        training_time_seconds, size_bytes, onnx_bytes,
    ))
    model_id = cursor.fetchone()[0]
    logger.info(
        "Stored atlas model id=%s (study='%s', target='%s', %s, %d bytes)",
        model_id, study, target_channel, architecture_type, size_bytes,
    )
    return model_id


def list_atlas_models(
    cursor: PsycopgCursor,
    study: str | None = None,
    target_channel: str | None = None,
) -> list[dict]:
    """
    Return model metadata (no ONNX bytes), newest first.

    Optionally filter by study and/or target_channel. Because versions are kept,
    the first row for a given (study, target_channel) is the most recent.
    """
    clauses = []
    params: list = []
    if study is not None:
        clauses.append("study = %s")
        params.append(study)
    if target_channel is not None:
        clauses.append("target_channel = %s")
        params.append(target_channel)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    columns = ", ".join(_METADATA_COLUMNS)
    cursor.execute(
        f"SELECT {columns} FROM atlas_model {where} ORDER BY created DESC, id DESC ;",
        tuple(params),
    )
    return [dict(zip(_METADATA_COLUMNS, row)) for row in cursor.fetchall()]


def get_atlas_model(cursor: PsycopgCursor, model_id: int) -> bytes | None:
    """Return the raw ONNX bytes for a stored model id, or None if absent."""
    cursor.execute("SELECT onnx_model FROM atlas_model WHERE id = %s ;", (model_id,))
    row = cursor.fetchone()
    return bytes(row[0]) if row is not None else None
