"""Explicit real-PostgreSQL fixtures; acceptance mode never silently skips."""

import os
import uuid

import pytest


@pytest.fixture(scope="session")
def postgres_dsn():
    required = os.environ.get("THESIS_CORE_REQUIRE_POSTGRES") == "1"
    dsn = os.environ.get("THESIS_CORE_TEST_DSN") or os.environ.get("THESIS_CORE_DSN")
    reason = (
        "Real PostgreSQL 14+ is required. Set THESIS_CORE_TEST_DSN or run "
        "python scripts/core_postgres.py -- uv run --extra core --extra dev pytest "
        "tests/thesis_core"
    )
    if not dsn:
        if required:
            pytest.fail(reason)
        pytest.skip(reason)
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=5) as connection:
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
            if version < 140000:
                raise RuntimeError("PostgreSQL is older than the supported version 14")
    except Exception as exc:
        message = f"{reason}. Connection failed: {type(exc).__name__}: {exc}"
        if required:
            pytest.fail(message)
        pytest.skip(message)
    return dsn


@pytest.fixture
def core_store(postgres_dsn, tmp_path):
    from psycopg import sql

    from thesis_core.artifacts import LocalArtifactStore
    from thesis_core.store import Store

    store = Store(
        postgres_dsn,
        LocalArtifactStore(tmp_path / "artifacts"),
        schema=f"test_core_{uuid.uuid4().hex}",
    )
    store.migrate()
    try:
        yield store
    finally:
        with store.connection() as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(store.schema))
            )
