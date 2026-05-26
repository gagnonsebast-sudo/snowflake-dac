#!/usr/bin/env python3
"""Scheduled anomaly check — Haiku, every Monday 08:00 ET.

Compares last week vs 4-week baseline for Allstate and MNP.
Threshold: ±15% deviation flags as anomaly.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

# SDK path is handled by the parent server (snowflake_dac_server.py).
# When run standalone, fall back to common locations.
if not any("irislabs" in p for p in sys.path):
    for _candidate in [
        os.path.join(os.path.expanduser("~"), "Documents", "Claude", "Projects", "IRIS", "report-generator", ".irislabs", "sdk"),
        os.path.join(os.path.expanduser("~"), "iris", "report-generator", ".irislabs", "sdk"),
    ]:
        if os.path.isdir(_candidate):
            sys.path.insert(0, os.path.abspath(_candidate))
            break

THRESHOLD = 0.15  # 15%

ALLSTATE_DB = "PROD_DB.ALLSTATE_CONSUMPTION"
MNP_DB = "PROD_DB.MNP_CONSUMPTION"


def last_monday() -> date:
    d = date.today()
    return d - timedelta(days=d.weekday() + 7)


def week_range(monday: date) -> tuple[date, date]:
    return monday, monday + timedelta(days=6)


def run_query(sql: str, client: str):
    from irislabs import data  # late import
    return data.query(sql, snowflake=client)


def _allstate_week_metrics(start: date, end: date) -> dict:
    sql = f"""
SELECT
    SUM(COST) AS spend,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS qq,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca
FROM {ALLSTATE_DB}.R_RPT_PAID_MEDIA
WHERE DATE BETWEEN '{start}' AND '{end}'
  AND DB_PLATFORM != 'client_leads'
"""
    dtc_sql = f"""
SELECT SUM(DTC_LEADS) AS dtc
FROM {ALLSTATE_DB}.R_FCT_PAID_MEDIA_CAMPAIGN
WHERE DATE BETWEEN '{start}' AND '{end}'
"""
    rows = run_query(sql, "ALLSTATE")
    dtc_rows = run_query(dtc_sql, "ALLSTATE")
    r = rows[0] if rows else {}
    spend = float(r.get("SPEND") or r.get("spend") or 0)
    qq = float(r.get("QQ") or r.get("qq") or 0)
    ca = float(r.get("CALLS_ADS") or r.get("calls_ads") or 0)
    ci = float(r.get("CALLS_INVOCA") or r.get("calls_invoca") or 0)
    dtc = float((dtc_rows[0].get("DTC") or dtc_rows[0].get("dtc") or 0)) if dtc_rows else 0
    leads = qq + ca + ci + dtc
    cpl = spend / leads if leads else None

    # QC region leads
    qc_sql = f"""
SELECT
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN QUICK_QUOTE ELSE 0 END)   AS qq,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_ADS ELSE 0 END)     AS calls_ads,
    SUM(CASE WHEN DB_PLATFORM='sa360' THEN CALLS_INVOCA ELSE 0 END)  AS calls_invoca
FROM {ALLSTATE_DB}.R_RPT_PAID_MEDIA
WHERE DATE BETWEEN '{start}' AND '{end}'
  AND DB_PLATFORM != 'client_leads'
  AND REGION = 'QC'
"""
    qc_rows = run_query(qc_sql, "ALLSTATE")
    qr = qc_rows[0] if qc_rows else {}
    qc_leads = (
        float(qr.get("QQ") or qr.get("qq") or 0)
        + float(qr.get("CALLS_ADS") or qr.get("calls_ads") or 0)
        + float(qr.get("CALLS_INVOCA") or qr.get("calls_invoca") or 0)
    )
    return {"spend": spend, "leads": leads, "cpl": cpl, "qc_leads": qc_leads}


def _mnp_week_metrics(start: date, end: date) -> dict | None:
    sql = f"""
SELECT
    SUM(COST) AS spend,
    SUM(PLATFORM_LEAD_TOTAL_CONVERSIONS) AS leads
FROM {MNP_DB}.R_RPT_PAID_MEDIA
WHERE DATE BETWEEN '{start}' AND '{end}'
"""
    try:
        rows = run_query(sql, "MNP")
    except Exception as e:
        if "C.CHANNELS" in str(e).upper() or "CHANNELS" in str(e).upper():
            return None  # blocker
        raise
    r = rows[0] if rows else {}
    spend = float(r.get("SPEND") or r.get("spend") or 0)
    leads = float(r.get("LEADS") or r.get("leads") or 0)
    cpl = spend / leads if leads else None

    # GA4 sessions
    sess_sql = f"""
SELECT SUM(SESSIONS) AS sessions
FROM {MNP_DB}.R_RPT_WEB_SESSIONS
WHERE DATE BETWEEN '{start}' AND '{end}'
"""
    try:
        sess_rows = run_query(sess_sql, "MNP")
        sessions = float((sess_rows[0].get("SESSIONS") or sess_rows[0].get("sessions") or 0)) if sess_rows else 0
    except Exception:
        sessions = None

    return {"spend": spend, "leads": leads, "cpl": cpl, "sessions": sessions}


def _avg(values: list[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def _check(label: str, current: float | None, baseline: float | None) -> tuple[bool, str]:
    if current is None or baseline is None or baseline == 0:
        return False, f"   {label}: données insuffisantes"
    delta = (current - baseline) / baseline
    sign = "+" if delta >= 0 else ""
    status = "OK" if abs(delta) <= THRESHOLD else "⚠️  ANOMALIE"
    line = f"   {label}: {_fmt(label, current)} ({sign}{delta*100:.1f}% vs baseline {_fmt(label, baseline)}) — {status}"
    return abs(delta) > THRESHOLD, line


def _fmt(label: str, v: float) -> str:
    if "spend" in label.lower() or "cpl" in label.lower():
        return f"${v:,.2f}"
    if "sessions" in label.lower():
        return f"{int(v):,}"
    return f"{int(v):,}"


def run_anomaly_check() -> str:
    target_monday = last_monday()
    target_start, target_end = week_range(target_monday)

    # Build 4-week baseline
    baseline_weeks = [
        week_range(target_monday - timedelta(weeks=i))
        for i in range(1, 5)
    ]

    output_lines = [
        f"🔍 IRIS Anomaly Check — sem. {target_start} → {target_end}",
        "",
    ]

    # ── Allstate ──
    try:
        current_a = _allstate_week_metrics(target_start, target_end)
        baselines_a = [_allstate_week_metrics(s, e) for s, e in baseline_weeks]
        baseline_a = {
            "spend": _avg([b["spend"] for b in baselines_a]),
            "leads": _avg([b["leads"] for b in baselines_a]),
            "cpl":   _avg([b["cpl"]   for b in baselines_a]),
            "qc_leads": _avg([b["qc_leads"] for b in baselines_a]),
        }

        anomalies_a = []
        lines_a = []
        for label, ck in [("Spend", "spend"), ("Leads", "leads"), ("CPL", "cpl"), ("Leads QC", "qc_leads")]:
            is_anom, line = _check(label, current_a[ck], baseline_a[ck])
            if is_anom:
                anomalies_a.append(label)
            lines_a.append(line)

        if anomalies_a:
            output_lines.append(f"⚠️  Allstate — {len(anomalies_a)} anomalie(s)")
        else:
            output_lines.append("✅ Allstate — RAS")
        output_lines.extend(lines_a)
    except Exception as e:
        if "auth" in str(e).lower():
            output_lines.append("❌ Allstate — Erreur auth IrisLabs")
        else:
            output_lines.append(f"❌ Allstate — Erreur: {e}")

    output_lines.append("")

    # ── MNP ──
    try:
        current_m = _mnp_week_metrics(target_start, target_end)
        if current_m is None:
            output_lines.append("⚠️  MNP — 1 anomalie")
            output_lines.append("   [BLOQUÉ] Vue R_RPT_PAID_MEDIA cassée (C.CHANNELS) — données indisponibles")
            output_lines.append("   → Contacter Bradly")
        else:
            baselines_m = [_mnp_week_metrics(s, e) for s, e in baseline_weeks]
            valid_baselines = [b for b in baselines_m if b is not None]
            baseline_m = {
                "spend":    _avg([b["spend"]    for b in valid_baselines]),
                "leads":    _avg([b["leads"]    for b in valid_baselines]),
                "cpl":      _avg([b["cpl"]      for b in valid_baselines]),
                "sessions": _avg([b["sessions"] for b in valid_baselines if b.get("sessions") is not None]),
            }

            anomalies_m = []
            lines_m = []
            checks = [("Spend", "spend"), ("Leads", "leads"), ("CPL", "cpl")]
            if current_m.get("sessions") is not None:
                checks.append(("Sessions GA4", "sessions"))

            for label, ck in checks:
                is_anom, line = _check(label, current_m.get(ck), baseline_m.get(ck))
                if is_anom:
                    anomalies_m.append(label)
                lines_m.append(line)

            if anomalies_m:
                output_lines.append(f"⚠️  MNP — {len(anomalies_m)} anomalie(s)")
            else:
                output_lines.append("✅ MNP — RAS")
            output_lines.extend(lines_m)
    except Exception as e:
        output_lines.append(f"❌ MNP — Erreur: {e}")

    return "\n".join(output_lines)


if __name__ == "__main__":
    print(run_anomaly_check())
