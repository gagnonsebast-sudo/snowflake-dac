# snowflake-dac

Claude Code plugin for **DAC Group** — accès aux performances paid media **Allstate** et **MNP** via Snowflake, directement depuis Cowork ou Claude Code.

## Installation

Depuis Claude Code web (`claude.ai/code`) :

1. **Plugins → Ajouter une marketplace**
2. URL : `gagnonsebast-sudo/snowflake-dac`
3. Synchroniser, puis cliquer **+** sur `snowflake-dac`
4. Renseigner les 3 champs requis :
   - `IRIS Control Plane URL`
   - `IrisLabs App ID`
   - `IRIS SDK Secret`

## Prérequis

- Python 3.10+
- SDK IrisLabs disponible localement. Le serveur le cherche dans cet ordre :
  1. Env var `IRISLABS_SDK_PATH` (optionnel — peut être ajouté via les paramètres du plugin)
  2. `${CLAUDE_PLUGIN_ROOT}/server/sdk/` (symlink local)
  3. `~/iris/report-generator/.irislabs/sdk/`
  4. `~/report-generator/.irislabs/sdk/`
- Si votre SDK est ailleurs, créez un symlink ou définissez `IRISLABS_SDK_PATH`.

## Tools exposés

**Allstate (11)** : `allstate_performance`, `allstate_conversion_breakdown`, `allstate_by_region`, `allstate_by_campaign`, `allstate_wow`, `allstate_pacing`, `allstate_language_split`, `allstate_category_split`, `allstate_daily_trend`, `allstate_top_campaigns`, `allstate_query`

**MNP (9)** : `mnp_performance`, `mnp_conversion_breakdown`, `mnp_by_channel`, `mnp_web_sessions`, `mnp_wow`, `mnp_invoca_reconciliation`, `mnp_daily_trend`, `mnp_by_ad_set`, `mnp_query`

**Anomaly check (1)** : `anomaly_check` — comparaison semaine vs baseline 4 semaines, seuil ±15%

## Skills

- `snowflake-allstate` — routing pour les questions Allstate
- `snowflake-mnp` — routing pour les questions MNP (avec gestion du blocker `C.CHANNELS`)
- `snowflake-query` — requêtes SQL custom avec guardrails

## Test rapide

> "Donne-moi les perfs Allstate des 7 derniers jours"

> "Comment va MNP cette semaine vs la semaine passée ?"

> "Breakdown par région Allstate — mois courant"

## Voir aussi

- `CLAUDE.md` — routing, conventions, conversions verrouillées
