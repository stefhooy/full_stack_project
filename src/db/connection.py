"""Connection management + the query safety boundary.

Two connection kinds, deliberately kept apart:
  - get_write_connection(): read-write, used ONLY by ingestion scripts.
  - get_read_only_connection(): read-only, used ONLY by the agent's SQL tool.

The read-only-ness is enforced twice, on purpose:
  1. DuckDB itself is opened with read_only=True — the engine physically
     refuses any write, independent of anything our Python code does.
  2. validate_select_only() below parses the SQL with a real parser
     (sqlglot) before it ever reaches DuckDB, and rejects anything that
     isn't a single SELECT statement against an allowlisted table.

Guard #2 exists even though guard #1 already blocks writes, because
read-only mode doesn't stop everything: a query can still ATTACH another
database file, COPY results out to disk, or chain multiple statements —
none of which "write to the games table" but all of which we don't want an
LLM-generated query ever doing. This is the one safety boundary in the
whole system, so it does not rely on prompting the model to behave; it
holds even if the model is adversarially prompted or just hallucinates.
"""

from __future__ import annotations

import duckdb
import sqlglot
from sqlglot import exp

from src.db.schema import ALLOWLISTED_TABLES


class UnsafeQueryError(ValueError):
    """Raised when a query fails the SELECT-only / allowlist guard."""


def get_write_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(db_path, read_only=False)


def get_read_only_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(db_path, read_only=True)


def _parse_single_select(sql: str) -> exp.Select:
    # sqlglot.parse() raises its own sqlglot.errors.ParseError for SQL that
    # doesn't even parse (as opposed to SQL that parses fine but fails the
    # SELECT-only/allowlist checks below) -- a real, previously-unhandled
    # gap, not a hypothetical one: ParseError isn't a ValueError subclass,
    # so it passed straight through execute_tools_node's
    # (UnsafeQueryError, duckdb.Error, ValueError) catch and the MCP
    # server's matching one, crashing both instead of feeding a normal,
    # self-correctable error back. Re-raising as UnsafeQueryError (itself
    # a ValueError) fixes every call site at once, at the one place this
    # safety boundary already lives, rather than patching each catcher.
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeQueryError(f"Could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeQueryError(
            f"Expected exactly one SQL statement, found {len(statements)}. "
            "Multi-statement queries are not allowed."
        )
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise UnsafeQueryError(
            f"Only SELECT statements are allowed, got a {type(tree).__name__} statement."
        )
    return tree


def _referenced_tables(tree: exp.Select) -> set[str]:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = set()
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if name and name not in cte_names:
            tables.add(name)
    return tables


def _enforce_row_cap(tree: exp.Select, max_rows: int) -> exp.Select:
    existing = tree.args.get("limit")
    if existing is None:
        return tree.limit(max_rows)
    try:
        existing_value = int(existing.expression.this)
    except (AttributeError, TypeError, ValueError):
        return tree.limit(max_rows)
    if existing_value > max_rows:
        return tree.limit(max_rows)
    return tree


def validate_select_only(sql: str, max_rows: int) -> str:
    """Parse `sql`, enforce SELECT-only + table allowlist + row cap, and
    return the (possibly rewritten) SQL string that is actually safe to run.

    Raises UnsafeQueryError with a human-readable reason on any violation —
    the agent's self-correction loop feeds that message back to the LLM the
    same way it would feed back a DuckDB execution error.
    """
    tree = _parse_single_select(sql)

    tables = _referenced_tables(tree)
    disallowed = tables - ALLOWLISTED_TABLES
    if disallowed:
        raise UnsafeQueryError(
            f"Query references table(s) not in the allowlist: {sorted(disallowed)}. "
            f"Allowed table(s): {sorted(ALLOWLISTED_TABLES)}."
        )

    capped_tree = _enforce_row_cap(tree, max_rows)
    return capped_tree.sql(dialect="duckdb")


def run_guarded_query(
    conn: duckdb.DuckDBPyConnection, sql: str, max_rows: int
) -> tuple[list[str], list[tuple]]:
    """Validate then execute `sql` on a read-only connection.

    Returns (column_names, rows). Rows are additionally truncated in Python
    to max_rows as a second belt on top of the injected SQL LIMIT.
    """
    safe_sql = validate_select_only(sql, max_rows)
    cursor = conn.execute(safe_sql)
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchmany(max_rows)
    return columns, rows
