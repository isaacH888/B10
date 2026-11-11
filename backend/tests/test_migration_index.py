import pymysql
import pytest

from app.migrations import MigrationError, run_command, statements


def test_runner_accepts_create_index_and_rejects_other_ddl(tmp_path):
    ok = tmp_path / "0009_idx.sql"
    ok.write_text("CREATE INDEX orders_event_start ON orders (event_starts_at);\n")
    assert len(statements(ok)) == 1
    for bad in ("ALTER TABLE orders ADD COLUMN x INT;", "DROP INDEX i ON orders;", "DROP TABLE orders;"):
        path = tmp_path / "0010_bad.sql"
        path.write_text(bad + "\n")
        with pytest.raises(MigrationError, match="resumable"):
            statements(path)


class FakeCursor:
    def __init__(self, code):
        self.code = code

    def execute(self, command):
        raise pymysql.err.OperationalError(self.code, "boom")


def test_existing_index_is_skipped_but_other_errors_are_not():
    run_command(FakeCursor(1061), "CREATE INDEX a ON orders (id)")
    with pytest.raises(pymysql.err.OperationalError):
        run_command(FakeCursor(1045), "CREATE INDEX a ON orders (id)")
