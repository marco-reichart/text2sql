"""SQLite helpers: find/download the database, run queries, describe the schema and validate generated SQL.

Locally the databases are read from `databases.local_dir` (config.yaml). On AWS (env DATABASE_BUCKET set) each
database is downloaded once from S3 to /tmp and reused by later requests of the same Lambda instance.
"""

import os
import re
import sqlite3
import time
from functools import cache
from pathlib import Path

import sqlglot
from sqlglot import exp

from config.config_loader import ConfigLoader

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TMP_DIR = Path("/tmp/databases")


def _download(bucket: str, db_id: str) -> Path:
    import boto3
    from botocore.exceptions import ClientError

    path = TMP_DIR / f"{db_id}.sqlite"
    if path.exists():
        return path
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{ConfigLoader.get()['databases']['s3_prefix']}{db_id}/{db_id}.sqlite"
    partial = path.with_suffix(".part")
    try:
        boto3.client("s3").download_file(bucket, key, str(partial))
    except ClientError as e:
        raise FileNotFoundError(db_id) from e
    partial.rename(path)
    return path


def database_path(db_id: str) -> Path:
    if not re.fullmatch(r"\w+", db_id):  # no paths like "../x"
        raise FileNotFoundError(db_id)
    bucket = os.getenv("DATABASE_BUCKET")
    if bucket:
        return _download(bucket, db_id)
    path = REPOSITORY_ROOT / ConfigLoader.get()["databases"]["local_dir"] / db_id / f"{db_id}.sqlite"
    if not path.exists():
        raise FileNotFoundError(db_id)
    return path


def connect(db_id: str) -> sqlite3.Connection:
    """Open the database read-only, so nothing can be modified even if validation misses something."""
    conn = sqlite3.connect(f"file:{database_path(db_id)}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode(errors="replace")  # some Spider DBs contain invalid UTF-8
    return conn


def execute_sql(sql: str, db_id: str) -> tuple[list[str], list[tuple]]:
    """Run the query with a time limit and return all rows as (columns, rows)."""
    timeout_s = ConfigLoader.get()["databases"]["query_timeout_s"]
    with connect(db_id) as conn:
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
        cursor = conn.execute(sql)
        rows = cursor.fetchall()
        columns = [d[0] for d in cursor.description]
    return columns, rows


@cache
def get_schema(db_id: str) -> str:
    """Get the schema incl. primary and foreign keys, e.g. `singer(Singer_ID INT PK, Name TEXT)`."""
    with connect(db_id) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        lines = []
        for table in tables:
            cols = [
                f"{name} {dtype}{' PK' if pk else ''}".strip()
                for _, name, dtype, _, _, pk in conn.execute(f'PRAGMA table_info("{table}")')
            ]
            lines.append(f"{table}({', '.join(cols)})")
            for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
                lines.append(f"  FK {table}.{fk[3]} -> {fk[2]}.{fk[4]}")
    return "\n".join(lines)


def validate_sql(sql: str, db_id: str) -> list[str]:
    """Return a list of errors; an empty list means the query is valid."""
    if not sql:
        return ["SQL is empty."]
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        return [f"Parse error: {e}"]
    if len(statements) != 1:
        return ["Exactly one SQL statement is required."]
    if not isinstance(statements[0], exp.Query):  # SELECT, WITH ... SELECT, UNION, ...
        return ["Only SELECT queries are allowed."]

    # SQLite compiles the query without running it: catches unknown tables/columns, bad functions, ...
    with connect(db_id) as conn:
        try:
            conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        except sqlite3.Error as e:
            return [f"SQLite error: {e}"]
    return []
