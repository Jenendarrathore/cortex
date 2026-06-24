"""Schema parity guard — no DB, no network.

db/schema.sql is the source of truth for DDL. The Python layer mirrors it twice:
ORM models (typed columns) and StrEnums (status/kind/level). Those mirrors drift
silently — add a column to schema.sql but not the model, or a JobStatus value
that no CHECK allows. These tests fail the moment they diverge.
"""
import re
from pathlib import Path

import pytest

from core.enums import JobKind, JobStatus, LogLevel
from models.document import Chunk, Document
from models.job import IngestionJob, JobLog

SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "rag-backend" / "db" / "schema.sql").read_text()


def _schema_columns(table: str) -> set[str]:
    """Column names declared for `table` in schema.sql (CREATE TABLE + ALTER ADD COLUMN)."""
    block = re.search(rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);", SCHEMA_SQL, re.DOTALL)
    assert block, f"table {table} not found in schema.sql"

    cols: set[str] = set()
    for line in block.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("--"):
            continue
        token = line.split()[0]
        if token.isidentifier():
            cols.add(token)

    for col in re.findall(rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS (\w+)", SCHEMA_SQL):
        cols.add(col)
    return cols


def _check_values(col: str) -> set[str]:
    """The allowed values from a `CHECK (<col> IN ('a','b',...))` constraint."""
    m = re.search(rf"{col}\s+TEXT.*?CHECK \({col} IN \(([^)]*)\)\)", SCHEMA_SQL)
    assert m, f"CHECK constraint for {col} not found in schema.sql"
    return set(re.findall(r"'([^']+)'", m.group(1)))


@pytest.mark.parametrize("model", [Document, Chunk, IngestionJob, JobLog])
def test_orm_columns_exist_in_schema(model):
    """Every column an ORM model declares must exist in schema.sql.

    (schema.sql may have extra DB-managed columns like chunks.fts — that's fine.)
    """
    table = model.__tablename__
    missing = set(model.__table__.columns.keys()) - _schema_columns(table)
    assert not missing, f"{table}: ORM columns absent from schema.sql: {sorted(missing)}"


def test_job_status_enum_matches_check():
    assert {s.value for s in JobStatus} == _check_values("status")


def test_job_kind_enum_matches_check():
    assert {k.value for k in JobKind} == _check_values("kind")


def test_log_level_enum_matches_check():
    assert {lvl.value for lvl in LogLevel} == _check_values("level")
