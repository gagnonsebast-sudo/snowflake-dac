"""Shared helpers: date parsing, query guard, IrisLabs connection."""
from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
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
MNP_WHITELIST = {"R_RPT_PAID_MEDIA", "R_RPT_PAIDMEDIA", "R_RPT_WEB_SESSIONS"}

MAX_ROWS = 10_000


def guard_sql(sql: str, whitelist: set[str]) -> str:
    """Validate and sanitize custom SQL. Returns cleaned SQL or raises."""
    if _DDL_PATTERN.search(sql):
        raise PermissionError("Read-only queries only — DDL/DML not permitted")

    upper = sql.upper()
    # Accept both unqualified names and FQN (DB.SCHEMA.TABLE) — only the leaf name is checked.
    mentioned = re.findall(r"\bFROM\s+([\w.]+)|\bJOIN\s+([\w.]+)", sql, re.IGNORECASE)
    tables = {t.split(".")[-1].strip('"').upper() for pair in mentioned for t in pair if t}
    unauthorized = {t for t in tables if t not in {v.upper() for v in whitelist}}
    if unauthorized:
        raise PermissionError("Query restricted to authorized views only")

    if "LIMIT" not in upper:
        sql = sql.rstrip().rstrip(";") + f"\nLIMIT {MAX_ROWS}"

    return sql


def qualify_views(sql: str, whitelist: set[str], prefix: str) -> str:
    """Prefix bare authorized view names in FROM/JOIN with DB.SCHEMA.

    The MNP Snowflake session has no default schema, so an unqualified name
    that guard_sql accepts still fails at execution with an obscure
    "does not exist or not authorized" (QA 2026-07-20, B8). Qualifying it
    here lets users write the short form safely. Already-qualified names and
    non-whitelisted names are left untouched.
    """
    allowed = {v.upper() for v in whitelist}

    def repl(m: re.Match) -> str:
        kw, name = m.group(1), m.group(2)
        if "." not in name and name.strip('"').upper() in allowed:
            return f"{kw} {prefix}.{name}"
        return m.group(0)

    return re.sub(r"\b(FROM|JOIN)\s+([\w.\"]+)", repl, sql, flags=re.IGNORECASE)


# ── Token validation ─────────────────────────────────────────────────────────

def check_token_expiry() -> tuple[bool, str]:
    """Decode JWT exp claim locally (no network). Returns (is_valid, message)."""
    token = os.environ.get("IRIS_SDK_SECRET", "")
    if not token:
        return False, "IRIS_SDK_SECRET non configuré"
    parts = token.split(".")
    if len(parts) != 3:
        return True, "Token présent (format non-JWT — impossible de vérifier l'expiration)"
    try:
        padding = (4 - len(parts[1]) % 4) % 4
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
        exp = payload.get("exp")
        if exp is None:
            return True, "Token présent (pas de claim exp)"
        now = time.time()
        exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        if now > exp:
            return False, f"Token expiré depuis {exp_dt} — appelle l'outil `iris_refresh` (ou : ~/.irislabs/bin/irislabs auth login)"
        remaining = int((exp - now) / 3600)
        return True, f"Token valide jusqu'au {exp_dt} ({remaining}h restantes)"
    except Exception:
        return True, "Token présent (impossible de décoder le JWT)"


# ── IrisLabs query wrapper ────────────────────────────────────────────────────

# Snowflake binding names — the EXACT strings granted to the app (see
# `irislabs snowflake bindings` from the app directory). Single source of truth:
# 3 scattered copies of a wrong literal ("MNP" — a binding that never existed;
# the real grant of 2026-05-13 is "MNP PROD", with the space) kept every mnp_*
# tool dead for two months. Do not inline these strings anywhere else.
ALLSTATE_BINDING = "ALLSTATE"
MNP_BINDING = "MNP PROD"

# MNP views — the canonical view has a broken DDL (typo `C.CHANNELS`; the source
# column is `CHANNEL`, singular). The sibling view R_RPT_PAIDMEDIA (no underscore
# between PAID and MEDIA) works and carries the same columns.
MNP_DB = "PROD_DB.MNP_CONSUMPTION"
MNP_MAIN_VIEW = f"{MNP_DB}.R_RPT_PAID_MEDIA"
MNP_FALLBACK_VIEW = f"{MNP_DB}.R_RPT_PAIDMEDIA"

MNP_BLOCKER_MSG = (
    "MNP data temporarily unavailable — view under maintenance (contact data engineering). "
    "Allstate is unaffected."
)


def is_channels_error(e: Exception) -> bool:
    """True ONLY for the exact broken-DDL signature of R_RPT_PAID_MEDIA.

    Strictly "C.CHANNELS": the broader match (invalid identifier + CHANNELS)
    also caught plugin/user SQL errors like `invalid identifier 'CHANNELS'`
    and converted them into the "view under maintenance" message — blaming
    data engineering for bugs that were 100% internal (QA 2026-07-20, B4).
    The canonical view was repaired upstream on 2026-07-20; the fallback is
    kept only as a safety net should the exact same typo ever reappear.
    """
    return "C.CHANNELS" in str(e).upper()


def run_query(sql: str, client: str) -> list[dict[str, Any]]:
    """Execute SQL via IrisLabs SDK. client = ALLSTATE_BINDING | MNP_BINDING."""
    from irislabs import data  # late import per pattern
    rows = data.query(sql, snowflake=client)
    return rows


def run_mnp_query(sql: str) -> list[dict[str, Any]]:
    """Run MNP SQL with automatic fallback to the working sibling view.

    If the canonical view fails with the C.CHANNELS DDL error, the query is
    retried on R_RPT_PAIDMEDIA. The blocker RuntimeError is raised only when
    BOTH views fail with the C.CHANNELS signature.

    Subtlety (QA v1.2.0, 1.4/N4): the canonical view's DDL still contains a
    residual `c.channels`, so ANY user error on it (e.g. an invalid column)
    forces Snowflake to compile the view body and surfaces C.CHANNELS instead
    of the user's real error. When the fallback then fails with a DIFFERENT
    error, that one is the user's actual mistake — surface it, don't hide it
    behind the "view under maintenance" message.
    """
    try:
        return run_query(sql, MNP_BINDING)
    except Exception as e:
        if is_channels_error(e):
            fallback_sql = sql.replace(MNP_MAIN_VIEW, MNP_FALLBACK_VIEW)
            if fallback_sql != sql:
                try:
                    return run_query(fallback_sql, MNP_BINDING)
                except Exception as fe:
                    if not is_channels_error(fe):
                        raise  # the user's real error, from the healthy view
            raise RuntimeError(MNP_BLOCKER_MSG) from e
        raise


def fmt_cad(v: float | None) -> str:
    if v is None:
        return "N/A"
    return f"${v:,.2f}"


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "N/A"
    sign = "+" if v and v >= 0 else ""
    return f"{sign}{v:.1f}%"


def fmt_pct_wow(v: float | None) -> str:
    """fmt_pct with a ⚠️ marker beyond ±10% — WoW deltas worth investigating."""
    s = fmt_pct(v)
    if v is not None and abs(v) > 10:
        s += " ⚠️"
    return s


def delta_pct(current: float, previous: float) -> float | None:
    if not previous:
        return None
    return (current - previous) / previous * 100


def safe_cpl(spend: float, leads: float) -> float | None:
    if not leads:
        return None
    return spend / leads
