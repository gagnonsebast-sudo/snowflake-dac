# Snowflake DAC — Context for Claude

This repo hosts the **snowflake-dac** Claude Code plugin: a Python MCP server exposing Allstate and MNP paid-media performance from Snowflake via the IrisLabs SDK (no direct Snowflake credentials).

## Client Routing — CRITICAL RULE

Before fetching any data, identify which client the user is asking about.

### Decision tree
1. User says "Allstate", "QC Allstate", "DTC", "Quick Quote" → Allstate tools (`allstate_*`)
2. User says "MNP", "Econofitness", "Mr. Lube", "Calls website (Invoca)" → MNP tools (`mnp_*`)
3. User says a generic term ("comment vont les perfs cette semaine") → ask which client, OR run both in parallel
4. NEVER mix Allstate and MNP in one calculation — they live in different Snowflake accounts

### Tool prefixes as a signal
- `allstate_*` → Allstate tools (Snowflake account `ALLSTATE`)
- `mnp_*` → MNP tools (Snowflake account `MNP`)
- `anomaly_check` → both clients in one weekly check

## Conversion definitions — LOCKED, do not modify

### Allstate
**Total leads = Quick Quote + Calls (ads) + Connected Calls (Invoca) + DTC**
- DTC sourced EXCLUSIVELY from `R_FCT_PAID_MEDIA_CAMPAIGN` (never `R_RAW_SA360.DTC_LEAD`)
- Meta `LEADS` reported separately as "Social", NEVER in Total
- Exclude `DB_PLATFORM = 'client_leads'` always

### MNP
**Total leads = PLATFORM_LEAD_TOTAL_CONVERSIONS** (already correct)
- `PLATFORM_LEAD_ON_FACEBOOK_LEADS` separate as "Social", NEVER in Total

## Known blockers

| Issue | Behavior |
|-------|----------|
| MNP view `R_RPT_PAID_MEDIA` returns `invalid identifier 'C.CHANNELS'` | Every MNP tool catches it and returns: *"MNP data temporarily unavailable — view under maintenance (contact data engineering). Allstate is unaffected."* — surface verbatim, do not retry. |
| IrisLabs SDK not found | Tools return: *"❌ SDK IrisLabs introuvable. Vérifie qu'il est présent à un emplacement standard..."* |
| `IRIS_SDK_SECRET` missing | Tools return: *"❌ IRIS_SDK_SECRET non configuré..."* → call `iris_refresh`. |
| **Token expired / "auth échouée" / tools return nothing** | **Call `iris_refresh` first.** It opens the IrisLabs login in the browser, then the fresh token is read automatically (no restart, no copy/paste). Retry the original request after login. |
| Snowflake timeout | Tools suggest a shorter date range. |

## If the plugin "bugs" — first reflex

Whenever a tool errors, returns empty, says the token is expired / auth failed, or
the tools seem to "disappear" — **call `iris_refresh` before anything else.** Most
plugin issues are an expired IrisLabs JWT (they last ~24h).

1. `iris_refresh` → opens the browser login → reads the new token live from
   `~/.irislabs/config.json`. No Claude Code restart, no manual token copy.
2. After the user completes the browser login, **retry the original request.**
3. `iris_ping` is the read-only diagnostic — run it to see SDK path, token expiry,
   and which source the token came from, without hitting Snowflake.

Only escalate to manual steps (`~/.irislabs/bin/irislabs login` in a terminal, or
editing `~/Documents/Claude/.snowflake-dac-credentials.json`) if `iris_refresh`
reports the CLI is unreachable.

## Date handling

Default period for any `*_performance` / breakdown tool: last 7 days (yesterday minus 6 → yesterday).

User shortcuts to interpret:
- "cette semaine" / "this week" → current week starting Monday
- "semaine dernière" / "last week" → previous Monday → Sunday
- "ce mois-ci" / "this month" → month-to-date (1st → yesterday)
- "depuis janvier" / "since January" → from Jan 1 of current year to yesterday

## Output format

Tools return pre-formatted markdown text — preserve formatting in your replies. Always include period covered. Highlight WoW deltas beyond ±10% as worth investigating.

## Architecture

```
plugins/snowflake-dac/
├── plugin.json              ← MCP server config + userConfig + SessionStart hook
├── server/
│   ├── snowflake_dac_server.py  ← FastMCP entry point, registers all tools
│   ├── shared.py            ← date helpers, query guard, IrisLabs wrapper
│   ├── allstate.py          ← 11 Allstate tools
│   ├── mnp.py               ← 9 MNP tools + blocker handling
│   ├── anomaly_check.py     ← weekly anomaly check
│   └── requirements.txt
└── skills/
    ├── snowflake-allstate/SKILL.md
    ├── snowflake-mnp/SKILL.md
    └── snowflake-query/SKILL.md
```
