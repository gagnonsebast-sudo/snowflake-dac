#!/usr/bin/env python3
"""MCP server for Snowflake DAC — Allstate & MNP paid media performance."""
from __future__ import annotations

import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

# Locate IrisLabs SDK — check candidate paths and add the first found to sys.path.
# Never sys.exit() if missing: tools return an explicit error instead.
_sdk_candidates = [
    os.environ.get("IRISLABS_SDK_PATH"),
    os.path.join(_here, "sdk"),
    os.path.join(_here, "..", "..", "..", "..", "report-generator", ".irislabs", "sdk"),
    os.path.join(os.path.expanduser("~"), "iris", "report-generator", ".irislabs", "sdk"),
    os.path.join(os.path.expanduser("~"), "report-generator", ".irislabs", "sdk"),
]
SDK_FOUND = None
for _candidate in _sdk_candidates:
    if _candidate and os.path.isdir(_candidate):
        SDK_FOUND = os.path.abspath(_candidate)
        sys.path.insert(0, SDK_FOUND)
        break

if not SDK_FOUND:
    print("⚠️  IrisLabs SDK introuvable. Les outils retourneront une erreur jusqu'à ce que le SDK soit installé.", file=sys.stderr)

if not os.environ.get("IRIS_SDK_SECRET"):
    print("⚠️  IRIS_SDK_SECRET non configuré. Les outils retourneront une erreur de config.", file=sys.stderr)

from mcp.server.fastmcp import FastMCP

import allstate as allstate_mod
import mnp as mnp_mod

mcp = FastMCP("snowflake-dac")


def _guard(fn, **kwargs) -> str:
    """Wrap tool calls: catch config/SDK errors and return clean message."""
    if not SDK_FOUND:
        return (
            "❌ SDK IrisLabs introuvable. Vérifie qu'il est présent à un emplacement standard "
            "(ex: ~/Documents/Claude/Projects/IRIS/report-generator/.irislabs/sdk) "
            "ou crée un lien symbolique vers ${CLAUDE_PLUGIN_ROOT}/server/sdk."
        )
    if not os.environ.get("IRIS_SDK_SECRET"):
        return "❌ IRIS_SDK_SECRET non configuré dans les paramètres du plugin."
    try:
        return fn(**kwargs)
    except ImportError as e:
        return f"❌ Import IrisLabs SDK échoué : {e}"
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return f"❌ Input invalide : {e}"
    except Exception as e:
        msg = str(e).lower()
        if "auth" in msg or "login" in msg or "unauthorized" in msg:
            return "❌ Authentification IrisLabs échouée. Vérifie IRIS_SDK_SECRET."
        if "timeout" in msg:
            return "❌ Snowflake timeout — essaye une plage de dates plus courte."
        return f"❌ Erreur : {e}"


# ── Allstate tools ────────────────────────────────────────────────────────────

@mcp.tool()
def allstate_performance(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """Allstate paid media performance over a period (spend, total leads, CPL, CTR, WoW delta).

    Args:
        date_from: ISO date YYYY-MM-DD (default: 7 days ago)
        date_to: ISO date YYYY-MM-DD (default: yesterday)
        group_by: total | region | platform | campaign_type | language | category
    """
    return _guard(allstate_mod.allstate_performance,
                  date_from=date_from, date_to=date_to, group_by=group_by)


@mcp.tool()
def allstate_conversion_breakdown(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Allstate conversion components: Quick Quote + Calls (ads) + Connected Calls + DTC + Meta Leads (separate)."""
    return _guard(allstate_mod.allstate_conversion_breakdown,
                  date_from=date_from, date_to=date_to)


@mcp.tool()
def allstate_by_region(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Allstate performance by region (ON, QC, NB, AB, etc.)."""
    return _guard(allstate_mod.allstate_by_region,
                  date_from=date_from, date_to=date_to)


@mcp.tool()
def allstate_by_campaign(
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
    platform: str | None = None,
    campaign_type: str | None = None,
    limit: int = 20,
) -> str:
    """Allstate campaign drill-down with optional filters (region, platform, campaign_type)."""
    return _guard(allstate_mod.allstate_by_campaign,
                  date_from=date_from, date_to=date_to,
                  region=region, platform=platform,
                  campaign_type=campaign_type, limit=limit)


@mcp.tool()
def allstate_wow(week_start: str | None = None) -> str:
    """Allstate week-over-week comparison (current week vs previous).

    Args:
        week_start: Monday ISO date (default: current week)
    """
    return _guard(allstate_mod.allstate_wow, week_start=week_start)


@mcp.tool()
def allstate_pacing(
    month: str | None = None,
    budget_total: float | None = None,
) -> str:
    """Allstate monthly budget pacing.

    Args:
        month: YYYY-MM (default: current month)
        budget_total: total monthly budget in CAD (required for delivery %, projection, status)
    """
    return _guard(allstate_mod.allstate_pacing,
                  month=month, budget_total=budget_total)


@mcp.tool()
def allstate_language_split(
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
) -> str:
    """Allstate FR vs EN performance — useful to isolate QC FR."""
    return _guard(allstate_mod.allstate_language_split,
                  date_from=date_from, date_to=date_to, region=region)


@mcp.tool()
def allstate_category_split(
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
) -> str:
    """Allstate Auto vs Home performance with conversion breakdown per category."""
    return _guard(allstate_mod.allstate_category_split,
                  date_from=date_from, date_to=date_to, region=region)


@mcp.tool()
def allstate_daily_trend(
    date_from: str | None = None,
    date_to: str | None = None,
    metric: str = "all",
    group_by: str = "total",
) -> str:
    """Allstate day-by-day trend — useful for anomaly detection, weekend effect, day-of-week patterns.

    Args:
        metric: all | spend | leads | cpl | clicks | impressions
        group_by: total | platform | region
    """
    return _guard(allstate_mod.allstate_daily_trend,
                  date_from=date_from, date_to=date_to,
                  metric=metric, group_by=group_by)


@mcp.tool()
def allstate_top_campaigns(
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "leads",
    limit: int = 10,
    region: str | None = None,
    platform: str | None = None,
) -> str:
    """Top Allstate campaigns by performance with delta vs previous period.

    Args:
        sort_by: spend | leads | cpl | clicks (default: leads)
    """
    return _guard(allstate_mod.allstate_top_campaigns,
                  date_from=date_from, date_to=date_to,
                  sort_by=sort_by, limit=limit,
                  region=region, platform=platform)


@mcp.tool()
def allstate_query(question: str) -> str:
    """Custom Allstate query — SELECT-only SQL against R_RPT_PAID_MEDIA or R_FCT_PAID_MEDIA_CAMPAIGN."""
    return _guard(allstate_mod.allstate_query, question=question)


# ── MNP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def mnp_performance(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """MNP paid media performance (spend, total leads from PLATFORM_LEAD_TOTAL_CONVERSIONS, CPL, WoW delta).

    Args:
        group_by: total | platform | channels | region | campaign_type
    """
    return _guard(mnp_mod.mnp_performance,
                  date_from=date_from, date_to=date_to, group_by=group_by)


@mcp.tool()
def mnp_conversion_breakdown(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """MNP conversion components: Form + Calls (ads) + Calls (web) + Facebook Leads (separate)."""
    return _guard(mnp_mod.mnp_conversion_breakdown,
                  date_from=date_from, date_to=date_to)


@mcp.tool()
def mnp_by_channel(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """MNP breakdown by channel (Paid Search / Paid Social / Display / etc.)."""
    return _guard(mnp_mod.mnp_by_channel,
                  date_from=date_from, date_to=date_to)


@mcp.tool()
def mnp_web_sessions(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """MNP GA4 web sessions: sessions, engagement, form submits, Invoca calls.

    Args:
        group_by: total | channel_group | paid_or_organic
    """
    return _guard(mnp_mod.mnp_web_sessions,
                  date_from=date_from, date_to=date_to, group_by=group_by)


@mcp.tool()
def mnp_wow(week_start: str | None = None) -> str:
    """MNP week-over-week comparison with breakdown Form/Calls/Facebook."""
    return _guard(mnp_mod.mnp_wow, week_start=week_start)


@mcp.tool()
def mnp_invoca_reconciliation(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """Compare Calls from ads (Invoca) vs Calls website (Invoca) — non-duplication check."""
    return _guard(mnp_mod.mnp_invoca_reconciliation,
                  date_from=date_from, date_to=date_to, group_by=group_by)


@mcp.tool()
def mnp_daily_trend(
    date_from: str | None = None,
    date_to: str | None = None,
    metric: str = "all",
) -> str:
    """MNP day-by-day trend (paid + GA4 sessions if metric includes sessions)."""
    return _guard(mnp_mod.mnp_daily_trend,
                  date_from=date_from, date_to=date_to, metric=metric)


@mcp.tool()
def mnp_by_ad_set(
    date_from: str | None = None,
    date_to: str | None = None,
    platform: str | None = None,
    campaign: str | None = None,
    limit: int = 20,
) -> str:
    """MNP drill-down at ad set level."""
    return _guard(mnp_mod.mnp_by_ad_set,
                  date_from=date_from, date_to=date_to,
                  platform=platform, campaign=campaign, limit=limit)


@mcp.tool()
def mnp_query(question: str) -> str:
    """Custom MNP query — SELECT-only SQL against R_RPT_PAID_MEDIA or R_RPT_WEB_SESSIONS."""
    return _guard(mnp_mod.mnp_query, question=question)


@mcp.tool()
def anomaly_check() -> str:
    """Run weekly anomaly check (Allstate + MNP) — current week vs 4-week baseline, ±15% threshold."""
    import anomaly_check as anomaly_mod
    return _guard(anomaly_mod.run_anomaly_check)


if __name__ == "__main__":
    mcp.run()
