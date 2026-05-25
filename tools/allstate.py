"""Allstate MCP tools — 11 tools."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .shared import (
    parse_date, default_date_range, current_week_start, prev_week_start,
    week_end, current_month_range, run_query, guard_sql, ALLSTATE_WHITELIST,
    fmt_cad, fmt_pct, delta_pct, safe_cpl, today, yesterday,
)

CLIENT = "ALLSTATE"
DB = "PROD_DB.ALLSTATE_CONSUMPTION"
MAIN_VIEW = f"{DB}.R_RPT_PAID_MEDIA"
CAMPAIGN_VIEW = f"{DB}.R_FCT_PAID_MEDIA_CAMPAIGN"

# Total leads (sa360 only, excl client_leads):
# QQ + CALLS_ADS + CALLS_INVOCA + DTC (from R_FCT_PAID_MEDIA_CAMPAIGN)
# Meta LEADS kept separate


def _dtc_sql(date_from: date, date_to: date) -> str:
    return f"""
SELECT SUM(DTC_LEADS) AS dtc
FROM {CAMPAIGN_VIEW}
WHERE DATE BETWEEN '{date_from}' AND '{date_to}'
"""


def _main_sql_period(date_from: date, date_to: date, extra_filter: str = "") -> str:
    where = f"DATE BETWEEN '{date_from}' AND '{date_to}' AND DB_PLATFORM != 'client_leads'"
    if extra_filter:
        where += f" AND {extra_filter}"
    return f"""
SELECT
    SUM(COST)          AS spend,
    SUM(CLICKS)        AS clicks,
    SUM(IMPRESSIONS)   AS impressions,
    SUM(CASE WHEN DB_PLATFORM = 'sa360' THEN QUICK_QUOTE ELSE 0 END)    AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM = 'sa360' THEN CALLS_ADS   ELSE 0 END)    AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM = 'sa360' THEN CALLS_INVOCA ELSE 0 END)   AS calls_invoca,
    SUM(CASE WHEN DB_PLATFORM = 'meta'  THEN LEADS        ELSE 0 END)   AS meta_leads
FROM {MAIN_VIEW}
WHERE {where}
"""


def _fetch_period(date_from: date, date_to: date, extra_filter: str = "") -> dict:
    rows = run_query(_main_sql_period(date_from, date_to, extra_filter), CLIENT)
    r = rows[0] if rows else {}
    dtc_rows = run_query(_dtc_sql(date_from, date_to), CLIENT)
    dtc = (dtc_rows[0].get("DTC") or dtc_rows[0].get("dtc") or 0) if dtc_rows else 0
    spend = float(r.get("SPEND") or r.get("spend") or 0)
    qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
    calls_ads = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
    calls_inv = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
    meta = float(r.get("META_LEADS") or r.get("meta_leads") or 0)
    total_leads = qq + calls_ads + calls_inv + float(dtc)
    return {
        "spend": spend,
        "clicks": float(r.get("CLICKS") or r.get("clicks") or 0),
        "impressions": float(r.get("IMPRESSIONS") or r.get("impressions") or 0),
        "quick_quote": qq,
        "calls_ads": calls_ads,
        "calls_invoca": calls_inv,
        "dtc": float(dtc),
        "meta_leads": meta,
        "total_leads": total_leads,
        "cpl": safe_cpl(spend, total_leads),
    }


def _header(date_from: date, date_to: date, title: str) -> str:
    return f"📊 {title} — {date_from} → {date_to}\n\n"


def _conversion_block(d: dict) -> str:
    lines = [
        "Conversion breakdown:",
        f"  Quick Quote:      {int(d['quick_quote']):,}",
        f"  Calls (ads):      {int(d['calls_ads']):,}",
        f"  Connected Calls:  {int(d['calls_invoca']):,}",
        f"  DTC:              {int(d['dtc']):,}",
        f"  {'─'*22}",
        f"  Total:            {int(d['total_leads']):,}",
        "",
        f"Social (exclu du total):",
        f"  Meta Leads:       {int(d['meta_leads']):,}",
    ]
    return "\n".join(lines)


# ── Tool functions ─────────────────────────────────────────────────────────────

def allstate_performance(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """Performance agrégée Allstate sur une période."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    if group_by == "total":
        cur = _fetch_period(start, end)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)
        prev = _fetch_period(prev_start, prev_end)

        ctr = (cur["clicks"] / cur["impressions"] * 100) if cur["impressions"] else 0

        out = _header(start, end, "Allstate")
        out += f"Spend:        {fmt_cad(cur['spend'])}\n"
        out += f"Total leads:  {int(cur['total_leads']):,}\n"
        out += f"CPL:          {fmt_cad(cur['cpl'])}\n"
        out += f"Clicks:       {int(cur['clicks']):,}\n"
        out += f"Impressions:  {int(cur['impressions']):,}\n"
        out += f"CTR:          {ctr:.2f}%\n\n"

        out += f"WoW vs {prev_start} → {prev_end}:\n"
        out += f"  Spend:  {fmt_pct(delta_pct(cur['spend'], prev['spend']))}\n"
        out += f"  Leads:  {fmt_pct(delta_pct(cur['total_leads'], prev['total_leads']))}\n"
        out += f"  CPL:    {fmt_pct(delta_pct(cur['cpl'] or 0, prev['cpl'] or 0))}\n\n"

        out += _conversion_block(cur)
        return out

    # group_by variants
    group_cols = {
        "region": "REGION",
        "platform": "PLATFORM",
        "campaign_type": "CAMPAIGN_TYPE",
        "language": "LANGUAGE",
        "category": "CATEGORY",
    }
    col = group_cols.get(group_by)
    if not col:
        raise ValueError(f"Invalid group_by '{group_by}' — valid: total|region|platform|campaign_type|language|category")

    sql = f"""
SELECT
    {col} AS grp,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(IMPRESSIONS) AS impressions,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END) AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)   AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END) AS calls_invoca,
    SUM(CASE WHEN DB_PLATFORM='meta'  THEN LEADS ELSE 0 END)       AS meta_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
  AND DB_PLATFORM != 'client_leads'
GROUP BY {col}
ORDER BY spend DESC
"""
    rows = run_query(sql, CLIENT)

    # DTC is not breakable by these dims — add total DTC proportionally (note caveat)
    dtc_rows = run_query(_dtc_sql(start, end), CLIENT)
    total_dtc = float((dtc_rows[0].get("DTC") or dtc_rows[0].get("dtc") or 0)) if dtc_rows else 0

    out = _header(start, end, f"Allstate — par {group_by}")
    out += f"{'Groupe':<30} {'Spend':>12} {'Leads':>8} {'CPL':>10} {'Clicks':>8} {'Impressions':>12}\n"
    out += "─" * 82 + "\n"
    for r in rows:
        grp = r.get("GRP") or r.get("grp") or "—"
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
        ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
        ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
        leads = qq + ca + ci  # DTC not breakable by dim
        cpl = safe_cpl(spend, leads)
        clicks = int(r.get("CLICKS") or r.get("clicks") or 0)
        imp = int(r.get("IMPRESSIONS") or r.get("impressions") or 0)
        out += f"{str(grp):<30} {fmt_cad(spend):>12} {int(leads):>8,} {fmt_cad(cpl):>10} {clicks:>8,} {imp:>12,}\n"
    out += f"\n⚠️  Leads excluent DTC (non ventilable par {group_by}) — DTC total période: {int(total_dtc):,}\n"
    return out


def allstate_conversion_breakdown(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Décomposition des 5 composantes de conversion Allstate."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))
    d = _fetch_period(start, end)

    out = _header(start, end, "Allstate — Conversion Breakdown")
    total = d["total_leads"]
    def pct(v):
        return f"{v/total*100:.1f}%" if total else "—"

    out += f"Quick Quote:        {int(d['quick_quote']):>8,}   ({pct(d['quick_quote'])})\n"
    out += f"Calls from ads:     {int(d['calls_ads']):>8,}   ({pct(d['calls_ads'])})\n"
    out += f"Connected Calls:    {int(d['calls_invoca']):>8,}   ({pct(d['calls_invoca'])})\n"
    out += f"DTC:                {int(d['dtc']):>8,}   ({pct(d['dtc'])})\n"
    out += "─" * 42 + "\n"
    out += f"Total leads:        {int(total):>8,}\n\n"
    out += f"Social (exclu du total):\n"
    out += f"  Meta Leads:       {int(d['meta_leads']):>8,}\n\n"
    out += f"Spend: {fmt_cad(d['spend'])}   CPL: {fmt_cad(d['cpl'])}\n"
    return out


def allstate_by_region(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Performance Allstate par région."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    sql = f"""
SELECT
    REGION,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(IMPRESSIONS) AS impressions,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca,
    SUM(CASE WHEN DB_PLATFORM='meta'  THEN LEADS ELSE 0 END)         AS meta_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
  AND DB_PLATFORM != 'client_leads'
GROUP BY REGION
ORDER BY spend DESC
"""
    rows = run_query(sql, CLIENT)
    dtc_rows = run_query(_dtc_sql(start, end), CLIENT)
    total_dtc = float((dtc_rows[0].get("DTC") or dtc_rows[0].get("dtc") or 0)) if dtc_rows else 0

    total_spend = sum(float(r.get("SPEND") or r.get("spend") or 0) for r in rows)

    out = _header(start, end, "Allstate — par Région")
    out += f"{'Région':<20} {'Spend':>12} {'% spend':>8} {'Leads*':>8} {'CPL':>10} {'Clicks':>8}\n"
    out += "─" * 70 + "\n"
    for r in rows:
        region = r.get("REGION") or "—"
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
        ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
        ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
        leads = qq + ca + ci
        cpl = safe_cpl(spend, leads)
        clicks = int(r.get("CLICKS") or r.get("clicks") or 0)
        pct_spend = spend / total_spend * 100 if total_spend else 0
        out += f"{str(region):<20} {fmt_cad(spend):>12} {pct_spend:>7.1f}% {int(leads):>8,} {fmt_cad(cpl):>10} {clicks:>8,}\n"
    out += f"\n* Leads excluent DTC (non ventilable par région) — DTC total: {int(total_dtc):,}\n"
    return out


def allstate_by_campaign(
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
    platform: str | None = None,
    campaign_type: str | None = None,
    limit: int = 20,
) -> str:
    """Drill-down campagne Allstate avec filtres optionnels."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    filters = [f"DATE BETWEEN '{start}' AND '{end}'", "DB_PLATFORM != 'client_leads'"]
    if region:
        filters.append(f"REGION = '{region}'")
    if platform:
        filters.append(f"PLATFORM = '{platform}'")
    if campaign_type:
        filters.append(f"CAMPAIGN_TYPE = '{campaign_type}'")

    where = " AND ".join(filters)
    sql = f"""
SELECT
    CAMPAIGN,
    PLATFORM,
    REGION,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca
FROM {MAIN_VIEW}
WHERE {where}
GROUP BY CAMPAIGN, PLATFORM, REGION
ORDER BY spend DESC
LIMIT {min(limit, 50)}
"""
    rows = run_query(sql, CLIENT)

    out = _header(start, end, "Allstate — Campagnes")
    if region:
        out += f"Région: {region}   "
    if platform:
        out += f"Plateforme: {platform}   "
    if campaign_type:
        out += f"Type: {campaign_type}"
    out += "\n\n"
    out += f"{'Campagne':<50} {'Plateforme':<15} {'Région':<10} {'Spend':>12} {'Leads*':>8} {'CPL':>10}\n"
    out += "─" * 108 + "\n"
    for r in rows:
        camp = str(r.get("CAMPAIGN") or r.get("campaign") or "—")[:49]
        plat = str(r.get("PLATFORM") or r.get("platform") or "—")[:14]
        reg = str(r.get("REGION") or r.get("region") or "—")[:9]
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
        ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
        ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
        leads = qq + ca + ci
        cpl = safe_cpl(spend, leads)
        out += f"{camp:<50} {plat:<15} {reg:<10} {fmt_cad(spend):>12} {int(leads):>8,} {fmt_cad(cpl):>10}\n"
    out += "\n* Leads = QQ+Calls (DTC non ventilable par campagne)\n"
    return out


def allstate_wow(week_start: str | None = None) -> str:
    """Comparaison semaine vs semaine précédente Allstate."""
    if week_start:
        ws = parse_date(week_start, current_week_start())
    else:
        ws = current_week_start()
    we = week_end(ws)
    pws = prev_week_start(ws)
    pwe = week_end(pws)

    cur = _fetch_period(ws, we)
    prev = _fetch_period(pws, pwe)

    out = f"📊 Allstate — WoW\n\n"
    out += f"Semaine courante:  {ws} → {we}\n"
    out += f"Semaine précédente: {pws} → {pwe}\n\n"

    def row(label, cur_v, prev_v, is_money=False, is_leads=False):
        fmt = fmt_cad if is_money else (lambda x: f"{int(x):,}" if x is not None else "N/A")
        d = delta_pct(cur_v or 0, prev_v or 0)
        return f"  {label:<20} {fmt(cur_v):>12}   {fmt(prev_v):>12}   {fmt_pct(d):>8}\n"

    out += f"{'Métrique':<22} {'Courante':>12}   {'Précédente':>12}   {'Delta':>8}\n"
    out += "─" * 60 + "\n"
    out += row("Spend", cur["spend"], prev["spend"], is_money=True)
    out += row("Total leads", cur["total_leads"], prev["total_leads"])
    out += row("CPL", cur["cpl"], prev["cpl"], is_money=True)
    out += row("Clicks", cur["clicks"], prev["clicks"])
    out += "\n"
    out += f"Conversion breakdown — Courante vs Précédente:\n"
    out += f"  {'Composante':<22} {'Courante':>10}   {'Précédente':>10}   {'Delta':>8}\n"
    out += "─" * 56 + "\n"
    for label, ck, pk in [
        ("Quick Quote", "quick_quote", "quick_quote"),
        ("Calls (ads)", "calls_ads", "calls_ads"),
        ("Connected Calls", "calls_invoca", "calls_invoca"),
        ("DTC", "dtc", "dtc"),
    ]:
        cv, pv = cur[ck], prev[pk]
        d = delta_pct(cv, pv)
        out += f"  {label:<22} {int(cv):>10,}   {int(pv):>10,}   {fmt_pct(d):>8}\n"
    out += "\n"
    out += f"Social (exclu):\n"
    out += f"  Meta Leads: {int(cur['meta_leads']):,} vs {int(prev['meta_leads']):,}\n"
    return out


def allstate_pacing(
    month: str | None = None,
    budget_total: float | None = None,
) -> str:
    """Pacing budget mensuel Allstate."""
    if month:
        year, m = map(int, month.split("-"))
        start = date(year, m, 1)
    else:
        start, _ = current_month_range()
        year, m = start.year, start.month

    import calendar
    days_in_month = calendar.monthrange(year, m)[1]
    end_of_month = date(year, m, days_in_month)
    today_d = today()
    period_end = min(yesterday(), end_of_month)

    sql = f"""
SELECT SUM(COST) AS spend
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{period_end}'
  AND DB_PLATFORM != 'client_leads'
"""
    rows = run_query(sql, CLIENT)
    actual_spend = float((rows[0].get("SPEND") or rows[0].get("spend") or 0)) if rows else 0

    days_elapsed = (period_end - start).days + 1
    days_remaining = (end_of_month - today_d).days

    out = f"📊 Allstate — Pacing {year}-{m:02d}\n\n"
    out += f"Spend actuel ({start} → {period_end}):  {fmt_cad(actual_spend)}\n"

    if budget_total:
        expected_to_date = budget_total * days_elapsed / days_in_month
        delivery_pct = actual_spend / budget_total * 100
        projected = actual_spend / days_elapsed * days_in_month if days_elapsed else 0
        gap = actual_spend - expected_to_date

        if delivery_pct < 90:
            status = "🔴 UNDER"
        elif delivery_pct > 110:
            status = "🔴 OVER"
        else:
            status = "✅ ON TRACK"

        out += f"Budget total:                         {fmt_cad(budget_total)}\n"
        out += f"Spend attendu pro-raté:               {fmt_cad(expected_to_date)}\n"
        out += f"% delivery:                           {delivery_pct:.1f}%\n"
        out += f"Gap vs attendu:                       {fmt_cad(gap)}\n"
        out += f"Projection fin de mois:               {fmt_cad(projected)}\n"
        out += f"Jours restants:                       {days_remaining}\n"
        out += f"Statut:                               {status}\n"
    else:
        out += f"Jours écoulés:  {days_elapsed} / {days_in_month}\n"
        out += f"⚠️  Passez budget_total (CAD) pour voir le pacing complet.\n"
    return out


def allstate_language_split(
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
) -> str:
    """Performance Allstate FR vs EN."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    filters = [f"DATE BETWEEN '{start}' AND '{end}'", "DB_PLATFORM != 'client_leads'"]
    if region:
        filters.append(f"REGION = '{region}'")
    where = " AND ".join(filters)

    sql = f"""
SELECT
    LANGUAGE,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca
FROM {MAIN_VIEW}
WHERE {where}
GROUP BY LANGUAGE
ORDER BY spend DESC
"""
    rows = run_query(sql, CLIENT)
    dtc_rows = run_query(_dtc_sql(start, end), CLIENT)
    total_dtc = float((dtc_rows[0].get("DTC") or dtc_rows[0].get("dtc") or 0)) if dtc_rows else 0

    total_spend = sum(float(r.get("SPEND") or r.get("spend") or 0) for r in rows)

    out = _header(start, end, f"Allstate — Langue{f' ({region})' if region else ''}")
    out += f"{'Langue':<10} {'Spend':>12} {'% total':>8} {'Leads*':>8} {'CPL':>10} {'Clicks':>8}\n"
    out += "─" * 60 + "\n"
    for r in rows:
        lang = r.get("LANGUAGE") or r.get("language") or "—"
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
        ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
        ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
        leads = qq + ca + ci
        cpl = safe_cpl(spend, leads)
        pct = spend / total_spend * 100 if total_spend else 0
        out += f"{str(lang):<10} {fmt_cad(spend):>12} {pct:>7.1f}% {int(leads):>8,} {fmt_cad(cpl):>10} {int(r.get('CLICKS') or r.get('clicks') or 0):>8,}\n"
    out += f"\n* Leads excluent DTC — DTC total: {int(total_dtc):,}\n"
    return out


def allstate_category_split(
    date_from: str | None = None,
    date_to: str | None = None,
    region: str | None = None,
) -> str:
    """Performance Allstate Auto vs Home."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    filters = [f"DATE BETWEEN '{start}' AND '{end}'", "DB_PLATFORM != 'client_leads'"]
    if region:
        filters.append(f"REGION = '{region}'")
    where = " AND ".join(filters)

    sql = f"""
SELECT
    CATEGORY,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca,
    SUM(CASE WHEN DB_PLATFORM='meta'  THEN LEADS ELSE 0 END)         AS meta_leads
FROM {MAIN_VIEW}
WHERE {where}
GROUP BY CATEGORY
ORDER BY spend DESC
"""
    rows = run_query(sql, CLIENT)
    dtc_rows = run_query(_dtc_sql(start, end), CLIENT)
    total_dtc = float((dtc_rows[0].get("DTC") or dtc_rows[0].get("dtc") or 0)) if dtc_rows else 0

    total_spend = sum(float(r.get("SPEND") or r.get("spend") or 0) for r in rows)

    out = _header(start, end, f"Allstate — Catégorie{f' ({region})' if region else ''}")
    out += f"{'Catégorie':<15} {'Spend':>12} {'% total':>8} {'Leads*':>8} {'CPL':>10} {'QQ':>8} {'Calls':>8} {'Meta':>8}\n"
    out += "─" * 82 + "\n"
    for r in rows:
        cat = r.get("CATEGORY") or r.get("category") or "—"
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
        ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
        ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
        meta = float(r.get("META_LEADS") or r.get("meta_leads") or 0)
        leads = qq + ca + ci
        cpl = safe_cpl(spend, leads)
        pct = spend / total_spend * 100 if total_spend else 0
        out += f"{str(cat):<15} {fmt_cad(spend):>12} {pct:>7.1f}% {int(leads):>8,} {fmt_cad(cpl):>10} {int(qq):>8,} {int(ca+ci):>8,} {int(meta):>8,}\n"
    out += f"\n* Leads excluent DTC — DTC total: {int(total_dtc):,}\n"
    return out


def allstate_daily_trend(
    date_from: str | None = None,
    date_to: str | None = None,
    metric: str = "all",
    group_by: str = "total",
) -> str:
    """Tendance jour par jour Allstate."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    group_sql = ""
    group_clause = ""
    if group_by != "total":
        col_map = {"platform": "PLATFORM", "region": "REGION"}
        col = col_map.get(group_by, "PLATFORM")
        group_sql = f", {col} AS grp"
        group_clause = f", {col}"

    sql = f"""
SELECT
    DATE{group_sql},
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(IMPRESSIONS) AS impressions,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS quick_quote,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
  AND DB_PLATFORM != 'client_leads'
GROUP BY DATE{group_clause}
ORDER BY DATE{group_clause}
"""
    rows = run_query(sql, CLIENT)

    out = _header(start, end, f"Allstate — Tendance journalière")
    if group_by == "total":
        out += f"{'Date':<12} {'Spend':>12} {'Leads*':>8} {'CPL':>10} {'Clicks':>8} {'CTR':>7}\n"
        out += "─" * 60 + "\n"
        for r in rows:
            d = str(r.get("DATE") or r.get("date") or "")[:10]
            spend = float(r.get("SPEND") or r.get("spend") or 0)
            qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
            ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
            ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
            leads = qq + ca + ci
            cpl = safe_cpl(spend, leads)
            clicks = int(r.get("CLICKS") or r.get("clicks") or 0)
            imp = float(r.get("IMPRESSIONS") or r.get("impressions") or 0)
            ctr = clicks / imp * 100 if imp else 0
            out += f"{d:<12} {fmt_cad(spend):>12} {int(leads):>8,} {fmt_cad(cpl):>10} {clicks:>8,} {ctr:>6.2f}%\n"
    else:
        out += f"{'Date':<12} {'Groupe':<20} {'Spend':>12} {'Leads*':>8}\n"
        out += "─" * 55 + "\n"
        for r in rows:
            d = str(r.get("DATE") or r.get("date") or "")[:10]
            grp = str(r.get("GRP") or r.get("grp") or "—")[:19]
            spend = float(r.get("SPEND") or r.get("spend") or 0)
            qq = float(r.get("QUICK_QUOTE") or r.get("quick_quote") or 0)
            ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
            ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
            leads = qq + ca + ci
            out += f"{d:<12} {grp:<20} {fmt_cad(spend):>12} {int(leads):>8,}\n"
    out += "\n* Leads excluent DTC\n"
    return out


def allstate_top_campaigns(
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "leads",
    limit: int = 10,
    region: str | None = None,
    platform: str | None = None,
) -> str:
    """Top campagnes Allstate par performance, avec delta vs période précédente."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))
    days = (end - start).days
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days)

    sort_map = {
        "spend": "spend",
        "leads": "leads_cur",
        "cpl": "cpl_cur",
        "clicks": "clicks",
    }
    order_col = sort_map.get(sort_by, "leads_cur")

    filters = ["DB_PLATFORM != 'client_leads'"]
    if region:
        filters.append(f"REGION = '{region}'")
    if platform:
        filters.append(f"PLATFORM = '{platform}'")
    extra = " AND ".join(filters)

    sql = f"""
WITH cur AS (
    SELECT CAMPAIGN, PLATFORM,
        SUM(COST) AS spend, SUM(CLICKS) AS clicks,
        SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS qq,
        SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS ca,
        SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS ci
    FROM {MAIN_VIEW}
    WHERE DATE BETWEEN '{start}' AND '{end}' AND {extra}
    GROUP BY CAMPAIGN, PLATFORM
),
prev AS (
    SELECT CAMPAIGN,
        SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS qq,
        SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS ca,
        SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS ci
    FROM {MAIN_VIEW}
    WHERE DATE BETWEEN '{prev_start}' AND '{prev_end}' AND {extra}
    GROUP BY CAMPAIGN
)
SELECT
    c.CAMPAIGN, c.PLATFORM,
    c.spend,
    c.clicks,
    c.qq + c.ca + c.ci AS leads_cur,
    CASE WHEN (c.qq+c.ca+c.ci) > 0 THEN c.spend/(c.qq+c.ca+c.ci) ELSE NULL END AS cpl_cur,
    p.qq + p.ca + p.ci AS leads_prev
FROM cur c
LEFT JOIN prev p ON c.CAMPAIGN = p.CAMPAIGN
ORDER BY {order_col} DESC NULLS LAST
LIMIT {min(limit, 50)}
"""
    rows = run_query(sql, CLIENT)

    out = _header(start, end, f"Allstate — Top {limit} campagnes (par {sort_by})")
    out += f"{'Campagne':<48} {'Plateforme':<15} {'Spend':>12} {'Leads*':>8} {'CPL':>10} {'Delta leads':>12}\n"
    out += "─" * 108 + "\n"
    for r in rows:
        camp = str(r.get("CAMPAIGN") or r.get("campaign") or "—")[:47]
        plat = str(r.get("PLATFORM") or r.get("platform") or "—")[:14]
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        leads_cur = float(r.get("LEADS_CUR") or r.get("leads_cur") or 0)
        leads_prev = float(r.get("LEADS_PREV") or r.get("leads_prev") or 0)
        cpl_cur = r.get("CPL_CUR") or r.get("cpl_cur")
        delta = delta_pct(leads_cur, leads_prev)
        out += f"{camp:<48} {plat:<15} {fmt_cad(spend):>12} {int(leads_cur):>8,} {fmt_cad(float(cpl_cur) if cpl_cur else None):>10} {fmt_pct(delta):>12}\n"
    out += "\n* Leads excluent DTC\n"
    return out


def allstate_query(question: str) -> str:
    """Requête custom Allstate — question en langage naturel ou SQL partiel."""
    question = question.strip()

    # If it looks like SQL, validate and run directly
    is_sql = question.upper().startswith("SELECT")
    if is_sql:
        try:
            safe_sql = guard_sql(question, ALLSTATE_WHITELIST)
        except PermissionError as e:
            return str(e)
        rows = run_query(safe_sql, CLIENT)
        if not rows:
            return "No data found for this query."
        headers = list(rows[0].keys())
        out = " | ".join(headers) + "\n" + "─" * (len(" | ".join(headers))) + "\n"
        for r in rows[:100]:
            out += " | ".join(str(r.get(h, "")) for h in headers) + "\n"
        if len(rows) > 100:
            out += f"\n... ({len(rows)} lignes total — affichage limité à 100)\n"
        return out

    return (
        "Pour une requête custom Allstate, passez du SQL SELECT valide.\n"
        f"Vues autorisées : {', '.join(sorted(ALLSTATE_WHITELIST))}\n"
        f"Question reçue : {question}"
    )
