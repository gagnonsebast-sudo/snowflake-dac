---
name: snowflake-allstate
description: Retrieve Allstate paid media performance data from Snowflake via IrisLabs — spend, leads, CPL, CTR, conversion breakdown, regional/language/category splits, campaign rankings, week-over-week, monthly pacing. Use when asked about Allstate ads performance, conversions, leads, CPL, budget pacing, regional splits (ON/QC/NB/AB), Auto vs Home, FR vs EN, or "comment va Allstate cette semaine". Do NOT use for MNP — use snowflake-mnp instead. Do NOT use for Search Ads 360 raw data — use the sa360-dac plugin instead.
---

# Snowflake — Allstate Performance

## When to use this skill

The user asks about **Allstate** paid media performance (any of):
- Spend / coût publicitaire
- Leads (Total leads, DTC, Quick Quote, Calls, Meta)
- CPL (cost per lead)
- Clicks, impressions, CTR
- Breakdown by region (ON, QC, NB, AB - Calgary, etc.)
- Auto vs Home (category)
- FR vs EN (language)
- Campaign or platform performance
- WoW comparison (semaine vs semaine précédente)
- Monthly pacing vs budget

## Conversion model — CRITICAL

**Total leads Allstate = Quick Quote + Calls (ads) + Connected Calls (Invoca) + DTC**

- Quick Quote, Calls (ads), Connected Calls come from `R_RPT_PAID_MEDIA` where `DB_PLATFORM = 'sa360'`
- DTC comes EXCLUSIVELY from `R_FCT_PAID_MEDIA_CAMPAIGN` (`SUM(DTC_LEADS)`)
- NEVER use `R_RAW_SA360.DTC_LEAD` (~11x inflated due to grain)
- `LEADS` column on `R_RPT_PAID_MEDIA` = Meta leads only → reported separately, NOT in Total
- Always exclude `DB_PLATFORM = 'client_leads'` (spend = $0)

## Tools available

| Tool | When to use |
|------|------------|
| `allstate_performance` | Overall numbers + WoW for a period |
| `allstate_conversion_breakdown` | Decompose Total leads into the 5 components |
| `allstate_by_region` | Per-province breakdown (ON, QC, NB, AB, etc.) |
| `allstate_by_campaign` | Top N campaigns with optional region/platform/type filters |
| `allstate_wow` | Week-over-week comparison (current vs previous week) |
| `allstate_pacing` | Monthly delivery % vs budget, projection, on-track / under / over |
| `allstate_language_split` | FR vs EN (useful for QC FR isolation) |
| `allstate_category_split` | Auto vs Home with category-level conversion breakdown |
| `allstate_daily_trend` | Day-by-day for anomaly detection / weekend effect |
| `allstate_top_campaigns` | Ranked campaigns with delta vs previous period |
| `allstate_query` | Custom SQL SELECT against R_RPT_PAID_MEDIA or R_FCT_PAID_MEDIA_CAMPAIGN |

## Protocol

### Step 1 — Identify the period
Default to last 7 days (yesterday minus 6). If user says "cette semaine", use current week starting Monday. If "ce mois-ci", use month-to-date.

### Step 2 — Pick the right tool
For a general "comment va Allstate", start with `allstate_performance` (group_by=total) — it returns spend, leads, CPL, CTR, WoW deltas, and the conversion breakdown in one call.

For specific dimensions, use the dedicated tool (region, language, category, etc.). Avoid running `allstate_performance` with multiple group_by — make separate calls.

### Step 3 — Present the result
The tools return pre-formatted markdown text. Surface it directly. Highlight any WoW delta beyond ±10% as worth investigating.

## Output Format

The tools format output as markdown tables / structured text. Always preserve the formatting in your reply.

## Limitations

- DTC cannot be broken down by region, platform, language, category, or campaign — only available at total/period level. Per-dimension Total leads exclude DTC; a footnote indicates the total DTC for the period.
- Meta Leads are tracked separately and NEVER added to Total leads.
- `client_leads` platform rows are excluded from every calculation.
