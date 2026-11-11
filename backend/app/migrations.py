"""Explicit, shared, additive MySQL migrations with resumable DDL and checksums."""

import hashlib
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

from .config import read_settings
from .database import connect

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class MigrationError(RuntimeError):
    """A migration cannot safely proceed."""


def migration_files(directory=MIGRATIONS):
    files = sorted(Path(directory).glob("*.sql"))
    if not files:
        raise MigrationError("No migrations were found")
    versions = []
    for path in files:
        match = re.fullmatch(r"(\d{4})_[a-z0-9_]+\.sql", path.name)
        if not match:
            raise MigrationError("Migration filenames must begin with a four-digit version")
        version = int(match.group(1))
        if version in versions:
            raise MigrationError("Duplicate migration version")
        versions.append(version)
    return files


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def statements(path):
    """The initial runner accepts only additive, independently rerunnable table DDL."""
    source = Path(path).read_text(encoding="utf-8")
    source = re.sub(r"(?m)^\s*--[^\n]*$", "", source)
    pieces = [piece.strip() for piece in source.split(";") if piece.strip()]
    if not pieces or any(
        not re.match(r"^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b", piece, re.I) for piece in pieces
    ):
        raise MigrationError("This runner requires resumable CREATE TABLE IF NOT EXISTS migrations")
    return pieces


def apply_migrations(settings, directory=MIGRATIONS):
    """Record intent before DDL so interrupted additive migrations can safely resume."""
    files = migration_files(directory)
    lock_name = "migrations:" + hashlib.sha256(settings["DB_NAME"].encode()).hexdigest()[:48]
    applied = []
    connection = connect(settings, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, 10) AS acquired", (lock_name,))
            if cursor.fetchone()["acquired"] != 1:
                raise MigrationError("Another migration runner holds the database lock")
            try:
                cursor.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INT UNSIGNED PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    checksum CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                    started_at BIGINT UNSIGNED NOT NULL,
                    applied_at BIGINT UNSIGNED NULL
                ) ENGINE=InnoDB""")
                cursor.execute(
                    "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
                )
                history = {row["version"]: row for row in cursor.fetchall()}
                versions = {int(path.name[:4]) for path in files}
                if set(history) - versions:
                    raise MigrationError("Database contains migrations unknown to this release")
                for path in files:
                    version = int(path.name[:4])
                    digest = checksum(path)
                    previous = history.get(version)
                    if previous and (
                        previous["checksum"] != digest or previous["name"] != path.name
                    ):
                        raise MigrationError(
                            "An existing migration has changed; restore its original contents"
                        )
                    if previous and previous["applied_at"] is not None:
                        continue
                    commands = statements(path)
                    cursor.execute(
                        "INSERT IGNORE INTO schema_migrations (version,name,checksum,started_at) VALUES (%s,%s,%s,%s)",
                        (version, path.name, digest, int(time.time())),
                    )
                    for command in commands:
                        cursor.execute(command)
                    cursor.execute(
                        "UPDATE schema_migrations SET applied_at=%s WHERE version=%s AND checksum=%s",
                        (int(time.time()), version, digest),
                    )
                    applied.append(path.name)
            finally:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
    finally:
        connection.close()
    return applied


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    settings = read_settings()
    migration_user = os.getenv("DB_MIGRATION_USER", "")
    migration_password = os.getenv("DB_MIGRATION_PASSWORD", "")
    if bool(migration_user) != bool(migration_password):
        raise MigrationError("Both migration credential settings are required together")
    if migration_user:
        settings.update(DB_USER=migration_user, DB_PASSWORD=migration_password)
    elif settings["APP_ENV"] != "development":
        raise MigrationError(
            "Hosted migrations require separate DB_MIGRATION_USER and DB_MIGRATION_PASSWORD"
        )
    applied = apply_migrations(settings)
    print("Migrations complete: " + (", ".join(applied) if applied else "already current"))


if __name__ == "__main__":
    main()
