import pymysql
import pytest
from app import database
from app.migrations import MigrationError, apply_migrations, run_command, statements
from test_auth_store import db_settings as db_settings


def test_runner_accepts_create_index_and_rejects_other_ddl(tmp_path):
    ok = tmp_path / "0009_idx.sql"
    ok.write_text("CREATE INDEX orders_event_start ON orders (event_starts_at);\n")
    assert len(statements(ok)) == 1
    for bad in (
        "ALTER TABLE orders ADD COLUMN x INT;",
        "DROP INDEX i ON orders;",
        "DROP TABLE orders;",
        "CREATE INDEX i ON orders (quote_id(10));",
        "CREATE INDEX i ON orders ((LOWER(quote_id)));",
        "CREATE INDEX i ON orders (quote_id) INVISIBLE;",
    ):
        path = tmp_path / "0010_bad.sql"
        path.write_text(bad + "\n")
        with pytest.raises(MigrationError, match="resumable"):
            statements(path)


class FakeCursor:
    def __init__(self, code):
        self.code = code

    def execute(self, command):
        raise pymysql.err.OperationalError(self.code, "boom")


@pytest.mark.parametrize("code", [1045, 1060, 1062, 1064])
def test_other_database_errors_are_not_ignored(code):
    with pytest.raises(pymysql.err.OperationalError):
        run_command(FakeCursor(code), "CREATE INDEX a ON orders (id)")


def test_duplicate_index_in_create_table_is_not_ignored():
    with pytest.raises(pymysql.err.OperationalError):
        run_command(
            FakeCursor(1061),
            "CREATE TABLE IF NOT EXISTS invalid_table (id INT, INDEX a (id), INDEX a (id))",
        )


@pytest.fixture
def index_probe(db_settings):
    with database.connect(db_settings, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE migration_index_probe (id INT, other_id INT)")
            try:
                yield cursor
            finally:
                cursor.execute("DROP TABLE migration_index_probe")


@pytest.mark.database
def test_index_can_resume_with_matching_definition(index_probe):
    command = "CREATE INDEX review_index ON migration_index_probe (id)"
    run_command(index_probe, command)
    run_command(index_probe, command)
    index_probe.execute("SHOW INDEX FROM migration_index_probe")
    rows = index_probe.fetchall()
    assert len(rows) == 1
    assert rows[0]["Column_name"] == "id"


@pytest.mark.database
def test_unique_composite_index_with_quoted_columns_can_resume(index_probe, tmp_path):
    command = (
        "CREATE UNIQUE INDEX `review_index` ON `migration_index_probe` (`id` DESC, other_id ASC)"
    )
    path = tmp_path / "0010_quoted_index.sql"
    path.write_text(command + ";\n")
    assert statements(path) == [command]
    run_command(index_probe, command)
    run_command(index_probe, command)
    index_probe.execute("SHOW INDEX FROM migration_index_probe")
    rows = index_probe.fetchall()
    assert [row["Column_name"] for row in rows] == ["id", "other_id"]
    assert [row["Collation"] for row in rows] == ["D", "A"]
    assert all(row["Non_unique"] == 0 for row in rows)


@pytest.mark.database
@pytest.mark.parametrize(
    "existing",
    [
        "CREATE INDEX review_index ON migration_index_probe (other_id)",
        "CREATE UNIQUE INDEX review_index ON migration_index_probe (id)",
        "CREATE INDEX review_index ON migration_index_probe (id, other_id)",
        "CREATE INDEX review_index ON migration_index_probe (id DESC)",
        "CREATE INDEX review_index ON migration_index_probe (id) INVISIBLE",
    ],
)
def test_conflicting_existing_index_is_not_silently_accepted(index_probe, existing):
    index_probe.execute(existing)
    with pytest.raises(MigrationError, match="different definition"):
        run_command(index_probe, "CREATE INDEX review_index ON migration_index_probe (id)")


@pytest.mark.database
def test_unique_index_failure_is_not_ignored(index_probe):
    index_probe.execute("INSERT INTO migration_index_probe (id) VALUES (1), (1)")
    with pytest.raises(pymysql.err.IntegrityError):
        run_command(index_probe, "CREATE UNIQUE INDEX review_index ON migration_index_probe (id)")


@pytest.mark.database
def test_interrupted_event_index_migration_resumes(db_settings):
    apply_migrations(db_settings)
    with (
        database.connect(db_settings, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("UPDATE schema_migrations SET applied_at=NULL WHERE version=9")
    assert apply_migrations(db_settings) == ["0009_orders_event_start_index.sql"]
    assert apply_migrations(db_settings) == []
    with database.connect(db_settings) as connection, connection.cursor() as cursor:
        cursor.execute("SHOW INDEX FROM orders WHERE Key_name='orders_event_start'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0]["Column_name"] == "event_starts_at"
        cursor.execute("SELECT applied_at FROM schema_migrations WHERE version=9")
        assert cursor.fetchone()["applied_at"] is not None
