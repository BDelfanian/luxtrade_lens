"""SQL guard: every query, compiled or LLM-written, passes here (SOLUTION_DESIGN §5.4).

One SELECT, whitelisted views only, no table functions or file paths, forced LIMIT. The DuckDB
connection is also read-only with external access disabled (defence in depth).
"""

import re

import sqlglot
from sqlglot import exp

from luxtrade.config import SQL_ROW_LIMIT
from luxtrade.semantic.catalog import ALLOWED_VIEWS

_FORBIDDEN_FUNCS = re.compile(
    r"^(read_|glob$|query$|query_table$|sniff_csv$|parquet_|iceberg_|delta_)"
)
_FILE_LITERAL = re.compile(
    r"(://|\b[\w\-./]+\.(parquet|csv|json|duckdb|db|txt|xlsx?)\b)",
    re.IGNORECASE,
)


class SQLRejectedError(ValueError):
    """Raised when a query breaks a guard rule."""


def check_sql(sql: str) -> str:
    """Validate ``sql``; return it normalised with a LIMIT or raise ``SQLRejectedError``."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise SQLRejectedError(f"could not parse SQL: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise SQLRejectedError("exactly one statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, exp.Select | exp.SetOperation):
        raise SQLRejectedError(f"only SELECT is allowed, got {type(stmt).__name__}")

    for node in stmt.walk():
        if isinstance(
            node,
            exp.Command
            | exp.Insert
            | exp.Update
            | exp.Delete
            | exp.Drop
            | exp.Create
            | exp.Alter
            | exp.Set
            | exp.Pragma
            | exp.Copy,
        ):
            raise SQLRejectedError(f"{type(node).__name__} is not allowed")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if _FORBIDDEN_FUNCS.match(name) or isinstance(node, exp.ReadCSV):
                raise SQLRejectedError(f"function {name} is not allowed")
        if isinstance(node, exp.Literal) and node.is_string and _FILE_LITERAL.search(node.this):
            raise SQLRejectedError("file paths and URLs are not allowed")

    ctes = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLRejectedError("qualified table names are not allowed")
        name = table.name.lower()
        if not name:
            raise SQLRejectedError("table functions are not allowed")
        if name not in ALLOWED_VIEWS and name not in ctes:
            raise SQLRejectedError(f"table {name} is not allowed (use the semantic views)")

    if isinstance(stmt, exp.Select):
        limit = stmt.args.get("limit")
        current = _limit_value(limit)
        if current is None or current > SQL_ROW_LIMIT:
            stmt = stmt.limit(SQL_ROW_LIMIT)
    else:
        stmt = exp.select("*").from_(stmt.subquery("u")).limit(SQL_ROW_LIMIT)
    return stmt.sql(dialect="duckdb", pretty=True)


def _limit_value(limit: exp.Expression | None) -> int | None:
    if limit is None:
        return None
    value = limit.expression if isinstance(limit, exp.Limit) else limit
    try:
        return int(value.this) if isinstance(value, exp.Literal) else None
    except (TypeError, ValueError):
        return None
