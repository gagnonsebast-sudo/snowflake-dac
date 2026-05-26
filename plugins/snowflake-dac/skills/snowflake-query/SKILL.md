---
name: snowflake-query
description: Run a custom SELECT-only SQL query against Snowflake (Allstate or MNP) via IrisLabs. Use when the user requests a specific ad-hoc query, a metric not exposed by the dedicated tools, or wants to combine fields not in standard breakdowns. Always pick the right client (Allstate vs MNP). Do NOT use for routine performance questions — use snowflake-allstate or snowflake-mnp dedicated tools instead.
---

# Snowflake — Custom Query

## When to use this skill

The user wants a SELECT query that isn't covered by the dedicated performance tools:
- Specific combinations of fields
- Filtering on unusual dimensions
- Joins across allowed views
- Ad-hoc exploration

For routine performance ("comment va Allstate cette semaine", "MNP par région"), use the dedicated skills — they are pre-validated with the locked conversion logic.

## Tools available

| Tool | Client | Allowed views |
|------|--------|---------------|
| `allstate_query` | Allstate | `R_RPT_PAID_MEDIA`, `R_FCT_PAID_MEDIA_CAMPAIGN` |
| `mnp_query` | MNP | `R_RPT_PAID_MEDIA`, `R_RPT_WEB_SESSIONS` |

## Guardrails

- SELECT only — DDL/DML rejected by regex BEFORE hitting Snowflake
- Only the whitelisted views are accessible — other tables raise an error
- `LIMIT 10000` is auto-injected if missing
- Always exclude `DB_PLATFORM = 'client_leads'` for Allstate unless explicitly required

## Protocol

### Step 1 — Identify the client
Allstate or MNP? If unclear, ask the user.

### Step 2 — Write a minimal SELECT
Use the table names without database prefix — they're resolved automatically per client. Be explicit about date filters.

### Step 3 — Submit and surface
Output is shown as a table (max 100 lines displayed). If truncated, the tool indicates how many rows were returned.

## Limitations

- No joins across Allstate and MNP (separate Snowflake accounts).
- No write operations.
- Results larger than 10 000 rows are capped — narrow your query.
