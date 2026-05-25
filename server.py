#!/usr/bin/env python3
"""MCP server — Snowflake DAC (IRIS) — stdio transport."""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any

import os

# Locate IrisLabs SDK — check several candidate paths in priority order
_here = os.path.dirname(os.path.abspath(__file__))
_sdk_candidates = [
    os.path.join(_here, "sdk"),                                               # deployed: ~/.config/snowflake-dac/sdk
    os.path.join(_here, "..", "report-generator", ".irislabs", "sdk"),        # dev: sibling repo
    os.path.join(os.path.expanduser("~"), "iris", "report-generator", ".irislabs", "sdk"),
    os.path.join(os.path.expanduser("~"), "report-generator", ".irislabs", "sdk"),
]
for _candidate in _sdk_candidates:
    if os.path.isdir(_candidate):
        sys.path.insert(0, os.path.abspath(_candidate))
        break

import tools.allstate as allstate_mod
import tools.mnp as mnp_mod

# ── Tool registry ──────────────────────────────────────────────────────────────

TOOLS: dict[str, dict] = {
    # ── Allstate ──
    "allstate_performance": {
        "fn": allstate_mod.allstate_performance,
        "description": "Performance agrégée Allstate (spend, leads, CPL, CTR, WoW delta).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "YYYY-MM-DD (défaut: -7j)"},
                "date_to":   {"type": "string", "description": "YYYY-MM-DD (défaut: hier)"},
                "group_by":  {"type": "string", "enum": ["total","region","platform","campaign_type","language","category"], "description": "Dimension d'agrégation"},
            },
        },
    },
    "allstate_conversion_breakdown": {
        "fn": allstate_mod.allstate_conversion_breakdown,
        "description": "Décomposition des 5 composantes de conversion Allstate (QQ, Calls ads, Connected Calls, DTC, Meta Leads).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
            },
        },
    },
    "allstate_by_region": {
        "fn": allstate_mod.allstate_by_region,
        "description": "Performance Allstate par région (ON, QC, NB, AB, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
            },
        },
    },
    "allstate_by_campaign": {
        "fn": allstate_mod.allstate_by_campaign,
        "description": "Drill-down campagnes Allstate avec filtres optionnels (région, plateforme, type).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from":     {"type": "string"},
                "date_to":       {"type": "string"},
                "region":        {"type": "string"},
                "platform":      {"type": "string"},
                "campaign_type": {"type": "string"},
                "limit":         {"type": "integer", "default": 20},
            },
        },
    },
    "allstate_wow": {
        "fn": allstate_mod.allstate_wow,
        "description": "Comparaison semaine vs semaine précédente Allstate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_start": {"type": "string", "description": "YYYY-MM-DD (lundi — défaut: semaine courante)"},
            },
        },
    },
    "allstate_pacing": {
        "fn": allstate_mod.allstate_pacing,
        "description": "Pacing budget mensuel Allstate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "month":        {"type": "string", "description": "YYYY-MM (défaut: mois courant)"},
                "budget_total": {"type": "number", "description": "Budget total CAD"},
            },
        },
    },
    "allstate_language_split": {
        "fn": allstate_mod.allstate_language_split,
        "description": "Performance Allstate FR vs EN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "region":    {"type": "string"},
            },
        },
    },
    "allstate_category_split": {
        "fn": allstate_mod.allstate_category_split,
        "description": "Performance Allstate Auto vs Home.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "region":    {"type": "string"},
            },
        },
    },
    "allstate_daily_trend": {
        "fn": allstate_mod.allstate_daily_trend,
        "description": "Tendance jour par jour Allstate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "metric":    {"type": "string", "enum": ["all","spend","leads","cpl","clicks","impressions"]},
                "group_by":  {"type": "string", "enum": ["total","platform","region"]},
            },
        },
    },
    "allstate_top_campaigns": {
        "fn": allstate_mod.allstate_top_campaigns,
        "description": "Top campagnes Allstate triées par performance, avec delta vs période précédente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "sort_by":   {"type": "string", "enum": ["spend","leads","cpl","clicks"]},
                "limit":     {"type": "integer", "default": 10},
                "region":    {"type": "string"},
                "platform":  {"type": "string"},
            },
        },
    },
    "allstate_query": {
        "fn": allstate_mod.allstate_query,
        "description": "Requête custom Allstate — SQL SELECT uniquement, vues R_RPT_PAID_MEDIA et R_FCT_PAID_MEDIA_CAMPAIGN.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "SQL SELECT ou question en langage naturel"},
            },
            "required": ["question"],
        },
    },
    # ── MNP ──
    "mnp_performance": {
        "fn": mnp_mod.mnp_performance,
        "description": "Performance paid media MNP (spend, leads, CPL, WoW delta).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "group_by":  {"type": "string", "enum": ["total","platform","channels","region","campaign_type"]},
            },
        },
    },
    "mnp_conversion_breakdown": {
        "fn": mnp_mod.mnp_conversion_breakdown,
        "description": "Décomposition Form / Calls ads / Calls web / Facebook Leads MNP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
            },
        },
    },
    "mnp_by_channel": {
        "fn": mnp_mod.mnp_by_channel,
        "description": "Breakdown MNP par canal (Paid Search, Paid Social, Display, etc.).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
            },
        },
    },
    "mnp_web_sessions": {
        "fn": mnp_mod.mnp_web_sessions,
        "description": "Données GA4 MNP — sessions, engagement, formulaires, appels Invoca.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "group_by":  {"type": "string", "enum": ["total","channel_group","paid_or_organic"]},
            },
        },
    },
    "mnp_wow": {
        "fn": mnp_mod.mnp_wow,
        "description": "Comparaison semaine vs semaine précédente MNP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "week_start": {"type": "string", "description": "YYYY-MM-DD (lundi)"},
            },
        },
    },
    "mnp_invoca_reconciliation": {
        "fn": mnp_mod.mnp_invoca_reconciliation,
        "description": "Compare Calls from ads vs Calls website (Invoca) MNP — validation de non-duplication.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "group_by":  {"type": "string", "enum": ["total","platform","region"]},
            },
        },
    },
    "mnp_daily_trend": {
        "fn": mnp_mod.mnp_daily_trend,
        "description": "Tendance jour par jour MNP (paid + GA4 sessions optionnel).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "metric":    {"type": "string", "enum": ["all","spend","leads","cpl","sessions"]},
            },
        },
    },
    "mnp_by_ad_set": {
        "fn": mnp_mod.mnp_by_ad_set,
        "description": "Drill-down MNP au niveau ad set.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to":   {"type": "string"},
                "platform":  {"type": "string"},
                "campaign":  {"type": "string"},
                "limit":     {"type": "integer", "default": 20},
            },
        },
    },
    "mnp_query": {
        "fn": mnp_mod.mnp_query,
        "description": "Requête custom MNP — SQL SELECT uniquement, vues R_RPT_PAID_MEDIA et R_RPT_WEB_SESSIONS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
        },
    },
}

# ── MCP protocol helpers ───────────────────────────────────────────────────────

def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _error(code: int, message: str, id: Any = None) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def _result(result: Any, id: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


# ── Request handlers ───────────────────────────────────────────────────────────

def handle_initialize(req: dict) -> dict:
    return _result(
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "snowflake-dac", "version": "0.1.0"},
        },
        req.get("id"),
    )


def handle_tools_list(req: dict) -> dict:
    tools_list = []
    for name, meta in TOOLS.items():
        tools_list.append(
            {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["inputSchema"],
            }
        )
    return _result({"tools": tools_list}, req.get("id"))


def handle_tools_call(req: dict) -> dict:
    params = req.get("params", {})
    name = params.get("name")
    args = params.get("arguments", {})
    req_id = req.get("id")

    if name not in TOOLS:
        return _error(-32601, f"Tool not found: {name}", req_id)

    try:
        result_text = TOOLS[name]["fn"](**args)
    except PermissionError as e:
        result_text = str(e)
    except ValueError as e:
        result_text = f"Invalid input: {e}"
    except Exception as e:
        tb = traceback.format_exc()
        # Detect auth errors
        if "auth" in str(e).lower() or "login" in str(e).lower():
            result_text = "irislabs auth login required — run in the IRIS project directory"
        elif "timeout" in str(e).lower():
            result_text = "Snowflake query timed out — try a shorter date range"
        else:
            result_text = f"Error: {e}\n{tb}"

    return _result(
        {"content": [{"type": "text", "text": result_text}]},
        req_id,
    )


# ── Main loop ──────────────────────────────────────────────────────────────────

HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError as e:
            _send(_error(-32700, f"Parse error: {e}"))
            continue

        method = req.get("method", "")
        handler = HANDLERS.get(method)
        if handler is None:
            _send(_error(-32601, f"Method not found: {method}", req.get("id")))
            continue

        try:
            response = handler(req)
        except Exception as e:
            response = _error(-32603, f"Internal error: {e}", req.get("id"))

        _send(response)


if __name__ == "__main__":
    main()
