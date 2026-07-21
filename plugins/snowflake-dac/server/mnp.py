"""MNP MCP tools — 9 tools."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from shared import (
    parse_date, default_date_range, current_week_start, prev_week_start,
    week_end, run_mnp_query, guard_sql, qualify_views, MNP_WHITELIST,
    MNP_BINDING, MNP_DB, MNP_MAIN_VIEW, MNP_BLOCKER_MSG,
    fmt_cad, fmt_pct, fmt_pct_wow, delta_pct, safe_cpl, yesterday,
)

# Binding name centralized in shared.py — NEVER hardcode "MNP" here, that
# binding does not exist (the real grant is "MNP PROD", with the space).
CLIENT = MNP_BINDING
DB = MNP_DB
MAIN_VIEW = MNP_MAIN_VIEW
WEB_VIEW = f"{DB}.R_RPT_WEB_SESSIONS"


def _mnp_run(sql: str) -> list[dict]:
    """MNP query with automatic fallback view — see shared.run_mnp_query."""
    return run_mnp_query(sql)


def _header(date_from, date_to, title: str) -> str:
    return f"📊 {title} — {date_from} → {date_to}\n\n"


def _wrap(fn, *args, **kwargs) -> str:
    try:
        return fn(*args, **kwargs)
    except RuntimeError as e:
        if MNP_BLOCKER_MSG in str(e):
            return str(e)
        raise


# ── Tool functions ─────────────────────────────────────────────────────────────

def mnp_performance(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """Performance paid media MNP."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    def _run(s, e, extra_group=""):
        group_col = ""
        group_clause = ""
        if extra_group:
            group_col = f", {extra_group} AS grp"
            group_clause = f", {extra_group}"
        sql = f"""
SELECT
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(IMPRESSIONS) AS impressions,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads,
    SUM(PLATFORM_LEAD_FORM_CONVERSIONS) AS form_leads,
    SUM(PLATFORM_LEAD_CALLS_FROM_ADS_INVOCA) AS calls_ads,
    SUM(PLATFORM_LEAD_CALLS_WEBSITE_INVOCA) AS calls_web,
    SUM(PLATFORM_LEAD_ON_FACEBOOK_LEADS) AS fb_leads{group_col}
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{s}' AND '{e}'
GROUP BY 1{group_clause if group_clause else ''}
ORDER BY spend DESC
"""
        # Fix group by syntax for total case
        if not extra_group:
            sql = f"""
SELECT
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(IMPRESSIONS) AS impressions,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads,
    SUM(PLATFORM_LEAD_FORM_CONVERSIONS) AS form_leads,
    SUM(PLATFORM_LEAD_CALLS_FROM_ADS_INVOCA) AS calls_ads,
    SUM(PLATFORM_LEAD_CALLS_WEBSITE_INVOCA) AS calls_web,
    SUM(PLATFORM_LEAD_ON_FACEBOOK_LEADS) AS fb_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{s}' AND '{e}'
"""
        return _mnp_run(sql)

    if group_by == "total":
        try:
            rows = _run(start, end)
            r = rows[0] if rows else {}
            spend = float(r.get("SPEND") or r.get("spend") or 0)
            total_leads = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
            cpl = safe_cpl(spend, total_leads)
            fb = float(r.get("FB_LEADS") or r.get("fb_leads") or 0)
            clicks = int(r.get("CLICKS") or r.get("clicks") or 0)
            imp = float(r.get("IMPRESSIONS") or r.get("impressions") or 0)
            ctr = clicks / imp * 100 if imp else 0

            days = (end - start).days
            prev_end = start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=days)
            prev_rows = _run(prev_start, prev_end)
            pr = prev_rows[0] if prev_rows else {}
            prev_spend = float(pr.get("SPEND") or pr.get("spend") or 0)
            prev_leads = float(pr.get("TOTAL_LEADS") or pr.get("total_leads") or 0)
            prev_cpl = safe_cpl(prev_spend, prev_leads)

            out = _header(start, end, "MNP")
            out += f"Spend:        {fmt_cad(spend)}\n"
            out += f"Total leads:  {round(total_leads):,}\n"
            out += f"CPL:          {fmt_cad(cpl)}\n"
            out += f"Clicks:       {clicks:,}\n"
            out += f"Impressions:  {int(imp):,}\n"
            out += f"CTR:          {ctr:.2f}%\n\n"
            out += f"WoW vs {prev_start} → {prev_end}:\n"
            out += f"  Spend:  {fmt_pct_wow(delta_pct(spend, prev_spend))}\n"
            out += f"  Leads:  {fmt_pct_wow(delta_pct(total_leads, prev_leads))}\n"
            out += f"  CPL:    {fmt_pct_wow(delta_pct(cpl or 0, prev_cpl or 0))}\n\n"
            out += f"Social (exclu du total):\n  Facebook Leads: {round(fb):,}\n"
            return out
        except RuntimeError as e:
            return str(e)

    # group_by variants
    group_map = {
        "platform": "PLATFORM",
        # Column is CHANNEL, singular, in both views — CHANNELS was a plugin
        # typo that killed this group_by (QA B2). API key stays "channels".
        "channels": "CHANNEL",
        "region": "REGION",
        "campaign_type": "CAMPAIGN_TYPE",
    }
    col = group_map.get(group_by)
    if not col:
        raise ValueError(f"Invalid group_by '{group_by}'")

    sql = f"""
SELECT
    {col} AS grp,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads,
    SUM(PLATFORM_LEAD_ON_FACEBOOK_LEADS) AS fb_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
GROUP BY {col}
ORDER BY spend DESC
"""
    try:
        rows = _mnp_run(sql)
    except RuntimeError as e:
        return str(e)

    total_spend = sum(float(r.get("SPEND") or r.get("spend") or 0) for r in rows)
    out = _header(start, end, f"MNP — par {group_by}")
    out += f"{'Groupe':<30} {'Spend':>12} {'% total':>8} {'Leads':>8} {'CPL':>10} {'FB Leads':>10}\n"
    out += "─" * 82 + "\n"
    for r in rows:
        grp = str(r.get("GRP") or r.get("grp") or "—")[:29]
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        leads = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
        fb = float(r.get("FB_LEADS") or r.get("fb_leads") or 0)
        cpl = safe_cpl(spend, leads)
        pct = spend / total_spend * 100 if total_spend else 0
        out += f"{grp:<30} {fmt_cad(spend):>12} {pct:>7.1f}% {round(leads):>8,} {fmt_cad(cpl):>10} {round(fb):>10,}\n"
    return out


def mnp_conversion_breakdown(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Décomposition Form / Calls (ads) / Calls (web) / Facebook Leads MNP."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    sql = f"""
SELECT
    SUM(COST) AS spend,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads,
    SUM(PLATFORM_LEAD_FORM_CONVERSIONS) AS form_leads,
    SUM(PLATFORM_LEAD_CALLS_FROM_ADS_INVOCA) AS calls_ads,
    SUM(PLATFORM_LEAD_CALLS_WEBSITE_INVOCA) AS calls_web,
    SUM(PLATFORM_LEAD_ON_FACEBOOK_LEADS) AS fb_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
"""
    try:
        rows = _mnp_run(sql)
    except RuntimeError as e:
        return str(e)

    r = rows[0] if rows else {}
    spend = float(r.get("SPEND") or r.get("spend") or 0)
    total = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
    form = float(r.get("FORM_LEADS") or r.get("form_leads") or 0)
    calls_ads = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
    calls_web = float(r.get("CALLS_WEB") or r.get("calls_web") or 0)
    fb = float(r.get("FB_LEADS") or r.get("fb_leads") or 0)
    cpl = safe_cpl(spend, total)

    def pct(v):
        return f"{v/total*100:.1f}%" if total else "—"

    out = _header(start, end, "MNP — Conversion Breakdown")
    out += f"Formulaire:              {round(form):>8,}   ({pct(form)})\n"
    out += f"Calls (ads - Invoca):    {round(calls_ads):>8,}   ({pct(calls_ads)})\n"
    out += f"Calls (web - Invoca):    {round(calls_web):>8,}   ({pct(calls_web)})\n"
    out += "─" * 42 + "\n"
    out += f"Total leads:             {round(total):>8,}\n\n"
    out += f"Social (exclu du total):\n"
    out += f"  Facebook Leads:        {round(fb):>8,}\n\n"
    out += f"Spend: {fmt_cad(spend)}   CPL: {fmt_cad(cpl)}\n"
    return out


def mnp_by_channel(
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Breakdown MNP par canal (Paid Search / Paid Social / Display / etc.)."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    sql = f"""
SELECT
    CHANNEL,
    SUM(COST) AS spend,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads,
    SUM(PLATFORM_LEAD_ON_FACEBOOK_LEADS) AS fb_leads,
    SUM(CLICKS) AS clicks
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
GROUP BY CHANNEL
ORDER BY spend DESC
"""
    try:
        rows = _mnp_run(sql)
    except RuntimeError as e:
        return str(e)

    total_spend = sum(float(r.get("SPEND") or r.get("spend") or 0) for r in rows)
    out = _header(start, end, "MNP — par Canal")
    out += f"{'Canal':<25} {'Spend':>12} {'% total':>8} {'Leads':>8} {'CPL':>10}\n"
    out += "─" * 66 + "\n"
    inactive = []
    for r in rows:
        channel = str(r.get("CHANNEL") or r.get("channel") or "—")[:24]
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        leads = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
        # Channels with zero spend AND zero leads clutter the table without
        # informing anyone (QA v1.2.0, N3) — list them in a footnote instead.
        if not spend and not leads:
            inactive.append(channel)
            continue
        cpl = safe_cpl(spend, leads)
        pct = spend / total_spend * 100 if total_spend else 0
        out += f"{channel:<25} {fmt_cad(spend):>12} {pct:>7.1f}% {round(leads):>8,} {fmt_cad(cpl):>10}\n"
    if inactive:
        out += f"\nCanaux inactifs sur la période (spend $0, 0 lead) : {', '.join(inactive)}\n"
    return out


def mnp_web_sessions(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """Données GA4 MNP — sessions, engagement, formulaires, appels."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    group_col = ""
    group_clause = ""
    if group_by != "total":
        col_map = {"channel_group": "CHANNEL_GROUP", "paid_or_organic": "PAID_OR_ORGANIC"}
        col = col_map.get(group_by, "CHANNEL_GROUP")
        group_col = f", {col} AS grp"
        group_clause = f", {col}"

    sql_total = f"""
SELECT
    SUM(SESSIONS) AS sessions,
    SUM(ENGAGED_SESSIONS) AS engaged,
    SUM(NEW_USERS) AS new_users,
    SUM(PAGE_VIEWS) AS page_views,
    SUM(LEAD_FORM_SUBMIT) AS form_submit,
    SUM(INVOCA_CALLS) AS invoca_calls{group_col}
FROM {WEB_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
{'GROUP BY ' + group_clause.strip(', ') if group_clause else ''}
ORDER BY sessions DESC
"""
    try:
        rows = _mnp_run(sql_total)
    except RuntimeError as e:
        return str(e)

    out = _header(start, end, f"MNP — Web Sessions (GA4)")
    if group_by == "total":
        r = rows[0] if rows else {}
        out += f"Sessions:          {int(r.get('SESSIONS') or r.get('sessions') or 0):,}\n"
        out += f"Engaged sessions:  {int(r.get('ENGAGED') or r.get('engaged') or 0):,}\n"
        out += f"New users:         {int(r.get('NEW_USERS') or r.get('new_users') or 0):,}\n"
        out += f"Page views:        {int(r.get('PAGE_VIEWS') or r.get('page_views') or 0):,}\n"
        out += f"Lead form submit:  {int(r.get('FORM_SUBMIT') or r.get('form_submit') or 0):,}\n"
        out += f"Invoca calls:      {int(r.get('INVOCA_CALLS') or r.get('invoca_calls') or 0):,}\n"
    else:
        out += f"{'Groupe':<30} {'Sessions':>10} {'Engaged':>10} {'Form Submit':>12} {'Invoca':>8}\n"
        out += "─" * 74 + "\n"
        for r in rows:
            grp = str(r.get("GRP") or r.get("grp") or "—")[:29]
            out += (
                f"{grp:<30} "
                f"{int(r.get('SESSIONS') or r.get('sessions') or 0):>10,} "
                f"{int(r.get('ENGAGED') or r.get('engaged') or 0):>10,} "
                f"{int(r.get('FORM_SUBMIT') or r.get('form_submit') or 0):>12,} "
                f"{int(r.get('INVOCA_CALLS') or r.get('invoca_calls') or 0):>8,}\n"
            )
    return out


def mnp_wow(week_start: str | None = None) -> str:
    """Comparaison semaine vs semaine précédente MNP."""
    # No local imports here: a `from shared import ... current_week_start`
    # inside the if-branch made the name function-local and crashed the else
    # branch with UnboundLocalError (QA B3). Module-level imports suffice.
    note = ""
    if week_start:
        ws = parse_date(week_start, current_week_start())
    else:
        ws = current_week_start()
        elapsed = (min(yesterday(), week_end(ws)) - ws).days + 1
        if elapsed <= 0:
            ws = prev_week_start(ws)
            note = "ℹ️  Semaine en cours sans journée complète de données — comparaison sur la dernière semaine complète.\n\n"
        elif elapsed < 7:
            note = f"⚠️  Semaine en cours incomplète ({elapsed}/7 jours de données) — deltas non comparables à une semaine pleine.\n\n"
    we = week_end(ws)
    pws = prev_week_start(ws)
    pwe = week_end(pws)

    def _fetch(s, e):
        sql = f"""
SELECT
    SUM(COST) AS spend,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads,
    SUM(PLATFORM_LEAD_FORM_CONVERSIONS) AS form_leads,
    SUM(PLATFORM_LEAD_CALLS_FROM_ADS_INVOCA) AS calls_ads,
    SUM(PLATFORM_LEAD_CALLS_WEBSITE_INVOCA) AS calls_web,
    SUM(PLATFORM_LEAD_ON_FACEBOOK_LEADS) AS fb_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{s}' AND '{e}'
"""
        return _mnp_run(sql)

    try:
        cur_rows = _fetch(ws, we)
        prev_rows = _fetch(pws, pwe)
    except RuntimeError as e:
        return str(e)

    def extract(rows):
        r = rows[0] if rows else {}
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        leads = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
        return {
            "spend": spend,
            "leads": leads,
            "cpl": safe_cpl(spend, leads),
            "form": float(r.get("FORM_LEADS") or r.get("form_leads") or 0),
            "calls_ads": float(r.get("CALLS_ADS") or r.get("calls_ads") or 0),
            "calls_web": float(r.get("CALLS_WEB") or r.get("calls_web") or 0),
            "fb": float(r.get("FB_LEADS") or r.get("fb_leads") or 0),
        }

    cur = extract(cur_rows)
    prev = extract(prev_rows)

    out = f"📊 MNP — WoW\n\n"
    out += f"Semaine courante:   {ws} → {we}\n"
    out += f"Semaine précédente: {pws} → {pwe}\n\n"
    out += note
    out += f"{'Métrique':<22} {'Courante':>12}   {'Précédente':>12}   {'Delta':>8}\n"
    out += "─" * 60 + "\n"
    for label, ck, pk, money in [
        ("Spend", "spend", "spend", True),
        ("Total leads", "leads", "leads", False),
        ("CPL", "cpl", "cpl", True),
    ]:
        cv, pv = cur[ck], prev[pk]
        fmt = fmt_cad if money else (lambda x: f"{round(x):,}" if x is not None else "N/A")
        d = delta_pct(cv or 0, pv or 0)
        out += f"  {label:<20} {fmt(cv):>12}   {fmt(pv):>12}   {fmt_pct(d):>8}\n"

    out += "\nConversion breakdown:\n"
    out += f"  {'Composante':<22} {'Courante':>10}   {'Précédente':>10}   {'Delta':>8}\n"
    out += "─" * 56 + "\n"
    for label, ck in [("Formulaire", "form"), ("Calls (ads)", "calls_ads"), ("Calls (web)", "calls_web")]:
        cv, pv = cur[ck], prev[ck]
        d = delta_pct(cv, pv)
        out += f"  {label:<22} {round(cv):>10,}   {round(pv):>10,}   {fmt_pct(d):>8}\n"
    out += f"\nSocial (exclu): Facebook Leads: {round(cur['fb']):,} vs {round(prev['fb']):,}\n"
    return out


def mnp_invoca_reconciliation(
    date_from: str | None = None,
    date_to: str | None = None,
    group_by: str = "total",
) -> str:
    """Compare Calls from ads (Invoca) vs Calls website (Invoca) MNP."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    group_col = ""
    group_clause = ""
    if group_by != "total":
        col_map = {"platform": "PLATFORM", "region": "REGION"}
        col = col_map.get(group_by, "PLATFORM")
        group_col = f", {col} AS grp"
        group_clause = f", {col}"

    sql = f"""
SELECT
    SUM(PLATFORM_LEAD_CALLS_FROM_ADS_INVOCA) AS calls_ads,
    SUM(PLATFORM_LEAD_CALLS_WEBSITE_INVOCA) AS calls_web{group_col}
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
{'GROUP BY ' + group_clause.strip(', ') if group_clause else ''}
ORDER BY calls_ads DESC
"""
    try:
        rows = _mnp_run(sql)
    except RuntimeError as e:
        return str(e)

    out = _header(start, end, "MNP — Réconciliation Invoca")
    if group_by == "total":
        r = rows[0] if rows else {}
        ads = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
        web = float(r.get("CALLS_WEB") or r.get("calls_web") or 0)
        ratio = ads / web if web else None
        out += f"Calls from ads (Invoca):    {round(ads):,}\n"
        out += f"Calls website (Invoca):     {round(web):,}\n"
        out += f"Ratio ads/web:              {f'{ratio:.2f}' if ratio else 'N/A'}\n"
        out += f"Delta:                      {round(ads - web):+,}\n"
    else:
        out += f"{'Groupe':<25} {'Calls ads':>12} {'Calls web':>12} {'Ratio':>8}\n"
        out += "─" * 60 + "\n"
        for r in rows:
            grp = str(r.get("GRP") or r.get("grp") or "—")[:24]
            ads = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
            web = float(r.get("CALLS_WEB") or r.get("calls_web") or 0)
            ratio = ads / web if web else None
            out += f"{grp:<25} {round(ads):>12,} {round(web):>12,} {f'{ratio:.2f}' if ratio else 'N/A':>8}\n"
    return out


def mnp_daily_trend(
    date_from: str | None = None,
    date_to: str | None = None,
    metric: str = "all",
) -> str:
    """Tendance jour par jour MNP."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    sql = f"""
SELECT
    DATE,
    SUM(COST) AS spend,
    SUM(CLICKS) AS clicks,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads
FROM {MAIN_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
GROUP BY DATE
ORDER BY DATE
"""
    try:
        rows = _mnp_run(sql)
    except RuntimeError as e:
        return str(e)

    include_sessions = metric in ("all", "sessions")
    session_data = {}
    if include_sessions:
        try:
            sess_sql = f"""
SELECT DATE, SUM(SESSIONS) AS sessions
FROM {WEB_VIEW}
WHERE DATE BETWEEN '{start}' AND '{end}'
GROUP BY DATE
ORDER BY DATE
"""
            sess_rows = _mnp_run(sess_sql)
            for r in sess_rows:
                d = str(r.get("DATE") or r.get("date") or "")[:10]
                session_data[d] = int(r.get("SESSIONS") or r.get("sessions") or 0)
        except Exception:
            pass

    out = _header(start, end, "MNP — Tendance journalière")
    out += f"{'Date':<12} {'Spend':>12} {'Leads':>8} {'CPL':>10} {'Clicks':>8}"
    if include_sessions:
        out += f" {'Sessions':>10}"
    out += "\n" + "─" * (52 + (10 if include_sessions else 0)) + "\n"

    for r in rows:
        d = str(r.get("DATE") or r.get("date") or "")[:10]
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        leads = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
        cpl = safe_cpl(spend, leads)
        clicks = int(r.get("CLICKS") or r.get("clicks") or 0)
        line = f"{d:<12} {fmt_cad(spend):>12} {round(leads):>8,} {fmt_cad(cpl):>10} {clicks:>8,}"
        if include_sessions:
            sess = session_data.get(d, 0)
            line += f" {sess:>10,}"
        out += line + "\n"
    return out


def mnp_by_ad_set(
    date_from: str | None = None,
    date_to: str | None = None,
    platform: str | None = None,
    campaign: str | None = None,
    limit: int = 20,
) -> str:
    """Drill-down MNP au niveau ad set."""
    end = parse_date(date_to, yesterday())
    start = parse_date(date_from, end - timedelta(days=6))

    filters = [f"DATE BETWEEN '{start}' AND '{end}'"]
    if platform:
        filters.append(f"PLATFORM = '{platform}'")
    if campaign:
        filters.append(f"CAMPAIGN = '{campaign}'")
    where = " AND ".join(filters)

    sql = f"""
SELECT
    AD_SET,
    CAMPAIGN,
    PLATFORM,
    SUM(COST) AS spend,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS total_leads
FROM {MAIN_VIEW}
WHERE {where}
GROUP BY AD_SET, CAMPAIGN, PLATFORM
ORDER BY spend DESC
LIMIT {min(limit, 50)}
"""
    try:
        rows = _mnp_run(sql)
    except RuntimeError as e:
        return str(e)

    out = _header(start, end, "MNP — Ad Sets")
    out += f"{'Ad Set':<35} {'Campagne':<35} {'Plateforme':<15} {'Spend':>12} {'Leads':>8} {'CPL':>10}\n"
    out += "─" * 118 + "\n"
    for r in rows:
        ad_set = str(r.get("AD_SET") or r.get("ad_set") or "—")[:34]
        camp = str(r.get("CAMPAIGN") or r.get("campaign") or "—")[:34]
        plat = str(r.get("PLATFORM") or r.get("platform") or "—")[:14]
        spend = float(r.get("SPEND") or r.get("spend") or 0)
        leads = float(r.get("TOTAL_LEADS") or r.get("total_leads") or 0)
        cpl = safe_cpl(spend, leads)
        out += f"{ad_set:<35} {camp:<35} {plat:<15} {fmt_cad(spend):>12} {round(leads):>8,} {fmt_cad(cpl):>10}\n"
    return out


def mnp_query(question: str) -> str:
    """Requête custom MNP — SQL SELECT valide uniquement."""
    question = question.strip()
    is_sql = question.upper().startswith("SELECT")
    if is_sql:
        try:
            safe_sql = guard_sql(question, MNP_WHITELIST)
        except PermissionError as e:
            return str(e)
        # The MNP session has no default schema — qualify bare view names so
        # accepted queries don't die in Snowflake with an obscure error (B8).
        safe_sql = qualify_views(safe_sql, MNP_WHITELIST, DB)
        try:
            rows = _mnp_run(safe_sql)
        except RuntimeError as e:
            return str(e)
        if not rows:
            return "No data found for this query."
        headers = list(rows[0].keys())
        out = " | ".join(headers) + "\n" + "─" * len(" | ".join(headers)) + "\n"
        for r in rows[:100]:
            out += " | ".join(str(r.get(h, "")) for h in headers) + "\n"
        if len(rows) > 100:
            out += f"\n... ({len(rows)} lignes total — affichage limité à 100)\n"
        return out

    return (
        "Pour une requête custom MNP, passez du SQL SELECT valide.\n"
        f"Vues autorisées : {', '.join(sorted(MNP_WHITELIST))}\n"
        f"Question reçue : {question}"
    )
