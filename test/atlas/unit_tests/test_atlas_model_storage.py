"""Unit tests for the atlas_model DB accessor, using a fake cursor (no database).

Full round-trip against Postgres is covered by the db module's harness; here we
check the SQL/parameters are well-formed and the return values are handled.
"""
from smprofiler.db.accessors.atlas_models import (
    store_atlas_model,
    list_atlas_models,
    get_atlas_model,
)


class _FakeCursor:
    """Records execute() calls; returns a canned row for fetchone/fetchall."""

    def __init__(self, one=None, all_rows=None):
        self.calls: list[tuple[str, tuple]] = []
        self._one = one
        self._all = all_rows or []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params) if params is not None else ()))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


def test_store_atlas_model_builds_insert_and_returns_id():
    cursor = _FakeCursor(one=(42,))
    onnx_bytes = b"onnx-model-bytes"
    model_id = store_atlas_model(
        cursor,
        study="luad",
        target_channel="FOXP3",
        input_channels=["CD4", "CD8"],
        architecture_type="gaussian_process",
        std_method="gaussian_posterior",
        onnx_input_dtype="float64",
        onnx_bytes=onnx_bytes,
        atlas_version="allen-2025",
        cv_r2=0.5, test_r2=0.4, test_mae=0.1,
        n_train=800, n_test=200, training_time_seconds=12.5,
    )
    assert model_id == 42
    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert "INSERT INTO atlas_model" in sql and "RETURNING id" in sql
    assert len(params) == 16, params
    assert params[0] == "luad" and params[1] == "FOXP3"
    assert params[2] == ["CD4", "CD8"]        # input_channels stays a list (-> text[])
    assert params[6] is True                  # onnx_has_std defaults to True
    assert params[14] == len(onnx_bytes)      # size_bytes derived from the bytes
    assert params[15] == onnx_bytes           # raw ONNX bytes last


def test_list_atlas_models_filters_and_orders():
    cursor = _FakeCursor(all_rows=[])
    list_atlas_models(cursor, study="luad", target_channel="FOXP3")
    sql, params = cursor.calls[0]
    assert "WHERE study = %s AND target_channel = %s" in sql
    assert "ORDER BY created DESC" in sql
    assert params == ("luad", "FOXP3")

    cursor = _FakeCursor(all_rows=[])
    list_atlas_models(cursor)
    sql, params = cursor.calls[0]
    assert "WHERE" not in sql
    assert params == ()


def test_get_atlas_model_returns_bytes_or_none():
    cursor = _FakeCursor(one=(b"abc",))
    assert get_atlas_model(cursor, 7) == b"abc"
    sql, params = cursor.calls[0]
    assert "SELECT onnx_model FROM atlas_model WHERE id = %s" in sql
    assert params == (7,)

    assert get_atlas_model(_FakeCursor(one=None), 999) is None


def main():
    test_store_atlas_model_builds_insert_and_returns_id()
    test_list_atlas_models_filters_and_orders()
    test_get_atlas_model_returns_bytes_or_none()
    print("atlas_model storage accessor: OK")


if __name__ == "__main__":
    main()
