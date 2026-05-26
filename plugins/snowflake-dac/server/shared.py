"""Shared helpers: date parsing, query guard, IrisLabs connection."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

# ── Date helpers ──────────────────────────────────────────────────────────────

def today() -> date:
    return date.today()


def yesterday() -> date:
    return today() - timedelta(days=1)


def parse_date(value: str | None, default: date) -> date:
    """Accept ISO date string or None; return date object."""
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid date '{value}' — expected YYYY-MM-DD")


def default_date_range() -> tuple[date, date]:
    """Return (7 days ago, yesterday)."""
    end = yesterday()
    start = end - timedelta(days=6)
    return start, end


def current_week_start() -> date:
    """Return last Monday (or today if Monday)."""
    d = today()
    return d - timedelta(days=d.weekday())


def prev_week_start(ref: date) -> date:
    return ref - timedelta(weeks=1)


def week_end(start: date) -> date:
    return start + timedelta(days=6)


def current_month_range() -> tuple[date, date]:
    d = today()
    start = d.replace(day=1)
    return start, yesterday()


# ── Query guard ───────────────────────────────────────────────────────────────

_DDL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|REPLACE|EXEC|EXECUTE|GRANT|REVOKE|CALL)\b",
    re.IGNORECASE,
)

ALLSTATE_WHITELIST = {"R_RPT_PAID_MEDIA", "R_FCT_PAID_MEDIA_CAMPAIGN"}
MNP_WHITELIST = {"R_RPT_PAID_MEDIA", "R_RPT_WEB_SESSIONS"}

MAX_ROWS = 10_000


def guard_sql(sql: str, whitelist: set[str]) -> str:
    """Validate and sanitize custom SQL. Returns cleaned SQL or raises."""
    if _DDL_PATTERN.search(sql):
        raise PermissionError("Read-only queries only — DDL/DML not permitted")

    upper = sql.upper()
    for view in whitelist:
        pass
    mentioned = re.findall(r"\bFROM\s+(\w+)\b|\bJOIN\s+(\w+)\b", sql, re.IGNORECASE)
    tables = {t for pair in mentioned for t in pair if t}
    unauthorized = {t for t in tables if t.upper() not in {v.upper() for v in whitelist}}
    if unauthorized:
        raise PermissionError("Query restricted to authorized views only")

    if "LIMIT" not in upper:
        sql = sql.rstrip().rstrip(";") + f"\nLIMIT {MAX_ROWS}"

    return sql


# ── IrisLabs query wrapper ────────────────────────────────────────────────────

def run_query(sql: str, client: str) -> list[dict[str, Any]]:
    """Execute SQL via IrisLabs SDK. client = 'ALLSTATE' | 'MNP'."""
    from irislabs import data  # late import per pattern
    rows = data.query(sql, snowflake=client)
    return rows


def fmt_cad(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"${v:,.2f}"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    sign = "+" if v and v >= 0 else ""
    return f"{sign}{v:.1f}%"


def delta_pct(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return (current - previous) / previous * 100


def safe_cpl(spend: float, leads: float) -> float | None:
    if not leads:
        return None
    return spend / leads
