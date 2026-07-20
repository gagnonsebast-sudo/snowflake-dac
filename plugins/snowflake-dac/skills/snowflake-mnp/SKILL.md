---
name: snowflake-mnp
description: Retrieve MNP paid media performance data from Snowflake via IrisLabs — spend, leads, CPL, conversion breakdown (Form / Calls ads / Calls web / Facebook), channel breakdown (Paid Search / Paid Social / Display), GA4 web sessions, ad set drill-down, Invoca reconciliation. Use when asked about MNP performance, conversions, leads, web sessions, channel mix, or "comment va MNP". Do NOT use for Allstate — use snowflake-allstate instead. Do NOT use for Search Ads 360 raw data — use the sa360-dac plugin instead.
---

# Snowflake — MNP Performance

## When to use this skill

The user asks about **MNP** paid media performance:
- Spend / coût publicitaire
- Leads (Total, Form, Calls from ads, Calls website, Facebook Leads)
- CPL
- Channel mix (Paid Search / Paid Social / Display)
- Platform mix (Google / Facebook / Microsoft)
- GA4 web sessions, engagement, form submissions, Invoca calls
- Ad set drill-down
- WoW comparison

## Conversion model — CRITICAL

**Total leads MNP = PLATFORM_LEAD_TOTAL_CONVERSIONS** (already correct in `R_RPT_PAID_MEDIA`)
- This sum = Form + Calls (ads) + Calls (website)
- `PLATFORM_LEAD_ON_FACEBOOK_LEADS` is reported SEPARATELY (social) — NOT included in Total

## Failure modes — two distinct ones, do not confuse them

### 1. Binding error (fails BEFORE any SQL runs)

> `External Snowflake database '<name>' not found for app <guid>`

The Snowflake binding name is wrong or not granted to the app. The correct MNP
binding is **`"MNP PROD"` — with the space** (granted 2026-05-13; a binding named
plain `"MNP"` has never existed). Diagnosis: run `irislabs snowflake bindings`
**from the app directory** — it is the ONLY reliable source of granted accesses.
(`irislabs snowflake list-available` lists the tenant's requestable connections,
NOT the app's grants — do not use it to diagnose this.)

### 2. Broken canonical view (fails DURING SQL)

> `invalid identifier 'C.CHANNELS'`

The canonical view `R_RPT_PAID_MEDIA` had a DDL typo — **repaired upstream on
2026-07-20** (both views now return identical counts). The automatic fallback
to the sibling view `R_RPT_PAIDMEDIA` (no underscore between PAID and MEDIA —
same columns, note `CHANNEL` singular) is kept as a safety net and only
triggers on the exact `C.CHANNELS` signature. Only if the fallback ALSO
fails do tools return:

> "MNP data temporarily unavailable — view under maintenance (contact data engineering). Allstate is unaffected."

If you see this message, surface it to the user verbatim and do not retry.

## Tools available

| Tool | When to use |
|------|------------|
| `mnp_performance` | Overall numbers + WoW |
| `mnp_conversion_breakdown` | Form / Calls ads / Calls web / Facebook split |
| `mnp_by_channel` | Paid Search / Paid Social / Display split |
| `mnp_web_sessions` | GA4 sessions, engagement, form submits, Invoca |
| `mnp_wow` | Week-over-week comparison |
| `mnp_invoca_reconciliation` | Calls from ads vs Calls website — non-duplication check |
| `mnp_daily_trend` | Day-by-day (paid + optional GA4 sessions) |
| `mnp_by_ad_set` | Ad set drill-down with platform/campaign filters |
| `mnp_query` | Custom SQL SELECT against R_RPT_PAID_MEDIA or R_RPT_WEB_SESSIONS |

## Protocol

### Step 1 — Identify the period
Default: last 7 days. Adjust for "cette semaine" (current Monday) or "ce mois-ci".

### Step 2 — Try the appropriate tool
If you receive the blocker message, stop and report it. Do not attempt to retry or use a different tool — they all hit the same view.

### Step 3 — Present the result
Surface the markdown output directly. Highlight Facebook Leads as social-only.

## Troubleshooting — first reflex if a tool bugs

If a tool errors, returns nothing, reports an expired token / auth failure, or the
tools seem to disappear: **call `iris_refresh` before anything else.** Most issues are
an expired IrisLabs JWT (~24h lifetime). `iris_refresh` opens the browser login and
reads the fresh token automatically — no restart, no copy/paste. After the user logs
in, retry the request. Use `iris_ping` for a read-only diagnostic.

Exception: the `C.CHANNELS` blocker message above is NOT a token issue — surface it
verbatim and do not call `iris_refresh`.

## Limitations

- MNP includes Econofitness and Mr. Lube which are not yet in Snowflake — those clients will return no data.
- GA4 web sessions are sourced from `R_RPT_WEB_SESSIONS`, separate from paid `R_RPT_PAID_MEDIA`.
- Facebook Leads are never included in Total leads.
