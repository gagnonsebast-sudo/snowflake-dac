#!/usr/bin/env python3
"""MCP server for Snowflake DAC — Allstate & MNP paid media performance."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

# ── Credentials ───────────────────────────────────────────────────────────────
# Priority order for IRIS_SDK_SECRET:
#   1. Credentials file (.snowflake-dac-credentials.json) — explicit SDK secret tied
#      to a specific app via IRISLABS_APP_ID. Takes highest priority; the IrisLabs CLI
#      token must NEVER overwrite it, because the CLI JWT carries resource_id="1" (tenant
#      root) which would override the app GUID and break all Snowflake queries.
#   2. Env var from plugin userConfig — also explicit, same rule applies.
#   3. IrisLabs CLI config (~/.irislabs/config.json) — CLI JWT (resource_id="1"). Used
#      as fallback only when no explicit SDK secret is available. `iris_refresh` rotates
#      this token automatically via `irislabs auth login`.
#
# IRISLABS_APP_ID, IRIS_CONTROL_PLANE_URL: filled from the first source that has them.

_CREDS_FILE_PATHS = [
    os.path.expanduser("~/mnt/Documents--Claude/.snowflake-dac-credentials.json"),
    os.path.expanduser("~/Documents/Claude/.snowflake-dac-credentials.json"),
    os.path.expanduser("~/.snowflake-dac-credentials.json"),
]

_IRIS_CONFIG_PATHS = [
    os.path.expanduser("~/.irislabs/config.json"),
    os.path.expanduser("~/mnt/Documents--Claude/.irislabs/config.json"),
]
_IRIS_CONFIG_KEY_MAP = {
    "Token": "IRIS_SDK_SECRET",
    "token": "IRIS_SDK_SECRET",
    "ControlPlaneUrl": "IRIS_CONTROL_PLANE_URL",
    "ControlPlaneURL": "IRIS_CONTROL_PLANE_URL",
    "controlPlaneUrl": "IRIS_CONTROL_PLANE_URL",
    "AppId": "IRISLABS_APP_ID",
    "AppID": "IRISLABS_APP_ID",
    "appId": "IRISLABS_APP_ID",
}

_CREDS_SOURCE: str | None = None         # static file that was loaded
_CREDS_HAS_TOKEN: bool = False           # True if the static file contained IRIS_SDK_SECRET
_IRIS_CONFIG_SOURCE: str | None = None   # live CLI config that supplied the token


def _load_static_credentials() -> None:
    """Load the static credentials file once. Only fills vars not already set."""
    global _CREDS_SOURCE, _CREDS_HAS_TOKEN
    for path in _CREDS_FILE_PATHS:
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        for key, val in data.items():
            if not os.environ.get(key):
                os.environ[key] = str(val)
        _CREDS_HAS_TOKEN = bool(data.get("IRIS_SDK_SECRET"))
        _CREDS_SOURCE = path
        return


def _iris_config_block(data: dict) -> dict:
    """Return the credential-bearing block of an IrisLabs config.json.

    v2 (CLI 2.x): { "ActiveEnvironment": "prod", "Environments": { "prod": {...} } }
        → the active environment block (or the first one if ActiveEnvironment is absent).
    v1 (older):   flat { "Token": ..., "ControlPlaneUrl": ... } → the dict itself.
    """
    envs = data.get("Environments")
    if isinstance(envs, dict) and envs:
        active = data.get("ActiveEnvironment")
        if active and active in envs and isinstance(envs[active], dict):
            return envs[active]
        for block in envs.values():
            if isinstance(block, dict):
                return block
    return data


def _sync_token_from_iris_config() -> bool:
    """Re-read the IrisLabs CLI config and refresh IRIS_SDK_SECRET from it.

    The CLI token rotates on every `irislabs auth login`. We only use it when no
    explicit SDK secret was provided in the credentials file — the SDK secret is tied
    to a specific app via IRISLABS_APP_ID, while the CLI JWT carries resource_id="1"
    (tenant root) which would break Snowflake routing if used as the auth token.

    Returns True if a CLI token was loaded. Safe to call repeatedly.
    Handles both v2 nested (Environments) and v1 flat IrisLabs config layouts.
    """
    global _IRIS_CONFIG_SOURCE
    for path in _IRIS_CONFIG_PATHS:
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        block = _iris_config_block(data)
        loaded = False
        for raw_key, env_key in _IRIS_CONFIG_KEY_MAP.items():
            val = block.get(raw_key)
            if not val:
                continue
            if env_key == "IRIS_SDK_SECRET":
                # Never overwrite an explicit SDK secret from the credentials file.
                # The CLI JWT's resource_id="1" would shadow the configured app GUID.
                if _CREDS_HAS_TOKEN:
                    continue
                os.environ[env_key] = str(val)
                loaded = True
            elif not os.environ.get(env_key):
                os.environ[env_key] = str(val)
        if loaded:
            _IRIS_CONFIG_SOURCE = path
            return True
    return False


_load_static_credentials()
_sync_token_from_iris_config()

# ── IrisLabs SDK ──────────────────────────────────────────────────────────────
# Locate SDK — check candidate paths; never sys.exit() if missing.
_sdk_candidates = [
    os.environ.get("IRISLABS_SDK_PATH"),
    os.path.join(_here, "sdk"),
    os.path.join(os.path.expanduser("~"), "mnt", "Documents--Claude", ".irislabs", "sdk"),
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

_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"[{_ts}] snowflake-dac MCP server starting", file=sys.stderr)
if _CREDS_SOURCE and _CREDS_HAS_TOKEN:
    print(f"[{_ts}] Token: SDK secret from credentials file {_CREDS_SOURCE}", file=sys.stderr)
elif _IRIS_CONFIG_SOURCE:
    print(f"[{_ts}] Token: CLI JWT from {_IRIS_CONFIG_SOURCE} (fallback — set IRIS_SDK_SECRET for app-specific auth)", file=sys.stderr)
elif _CREDS_SOURCE:
    print(f"[{_ts}] Credentials: loaded from file {_CREDS_SOURCE} (no token)", file=sys.stderr)
else:
    print(f"[{_ts}] Credentials: from env vars (or not set)", file=sys.stderr)

if not SDK_FOUND:
    print(f"[{_ts}] ⚠️  IrisLabs SDK introuvable. Les outils retourneront une erreur.", file=sys.stderr)
else:
    print(f"[{_ts}] SDK found: {SDK_FOUND}", file=sys.stderr)

if not os.environ.get("IRIS_SDK_SECRET"):
    print(f"[{_ts}] ⚠️  IRIS_SDK_SECRET non configuré. Les outils retourneront une erreur de config.", file=sys.stderr)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    import subprocess
    _installed = False
    for _pip in [
        [sys.executable, "-m", "pip", "install", "-q", "mcp[cli]>=1.0.0"],
        [sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "mcp[cli]>=1.0.0"],
        [sys.executable, "-m", "pip", "install", "-q", "--user", "mcp[cli]>=1.0.0"],
    ]:
        if subprocess.run(_pip, capture_output=True).returncode == 0:
            _installed = True
            break
    if not _installed:
        print(
            f"[{_ts}] ❌ Impossible d'installer mcp. Lance manuellement: pip3 install 'mcp[cli]>=1.0.0'",
            file=sys.stderr,
        )
        sys.exit(1)
    from mcp.server.fastmcp import FastMCP

import allstate as allstate_mod
import mnp as mnp_mod
import shared

mcp = FastMCP("snowflake-dac")

if os.environ.get("IRIS_SDK_SECRET"):
    _tok_valid, _tok_msg = shared.check_token_expiry()
    print(f"[{_ts}] Token: {_tok_msg}", file=sys.stderr)


def _guard(fn, **kwargs) -> str:
    """Wrap tool calls: catch config/SDK errors and return clean message."""
    if not SDK_FOUND:
        return (
            "❌ SDK IrisLabs introuvable. Vérifie qu'il est présent à un emplacement standard "
            "(ex: ~/Documents/Claude/Projects/IRIS/report-generator/.irislabs/sdk) "
            "ou crée un lien symbolique vers ${CLAUDE_PLUGIN_ROOT}/server/sdk."
        )
    if not os.environ.get("IRIS_SDK_SECRET"):
        _sync_token_from_iris_config()
    if not os.environ.get("IRIS_SDK_SECRET"):
        return (
            "❌ IRIS_SDK_SECRET non configuré. Lance l'outil `iris_refresh` "
            "ou configure les credentials IrisLabs."
        )
    tok_valid, tok_msg = shared.check_token_expiry()
    if not tok_valid:
        # The user may have just run `irislabs auth login` — re-read the live config.
        _sync_token_from_iris_config()
        tok_valid, tok_msg = shared.check_token_expiry()
    if not tok_valid:
        return (
            f"❌ {tok_msg}\n"
            "→ Appelle l'outil `iris_refresh` pour rafraîchir le token sans quitter Claude."
        )
    app_id = os.environ.get("IRISLABS_APP_ID", "").strip()
    if not app_id:
        return (
            "❌ IRISLABS_APP_ID non configuré.\n"
            "→ Ajoute ton App ID IrisLabs (GUID, ex: b5d26977-481a-4f61-bf7c-b2f8cedf47fe) "
            "dans le champ 'IrisLabs App ID' du plugin, ou dans "
            "`~/Documents/Claude/.snowflake-dac-credentials.json` (clé `IRISLABS_APP_ID`).\n"
            "→ Lance `iris_ping` pour diagnostiquer la configuration complète."
        )
    if app_id == "1":
        return (
            "❌ IRISLABS_APP_ID est '1' — c'est l'ID racine du tenant, pas un App ID valide.\n"
            "→ Utilise le GUID de ton app (ex: b5d26977-481a-4f61-bf7c-b2f8cedf47fe).\n"
            "→ Pour trouver tes apps : `irislabs app list` dans le terminal.\n"
            "→ Mets à jour le champ 'IrisLabs App ID' dans les paramètres du plugin "
            "ou dans `~/Documents/Claude/.snowflake-dac-credentials.json`."
        )
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
        # Sanitize SDK error messages that reference non-existent CLI commands.
        raw = str(e).replace(
            "irislabs snowflake external list",
            "irislabs snowflake list-available",
        )
        if "not found for app" in msg or "external snowflake database" in msg:
            return (
                f"❌ App ID IrisLabs invalide ou sans accès Snowflake (IRISLABS_APP_ID='{app_id}').\n"
                "→ Vérifie que l'app a les bindings Snowflake requis (ALLSTATE / MNP PROD — avec l'espace).\n"
                "→ `irislabs snowflake bindings` (depuis le répertoire de ton app) — SEULE source fiable des accès accordés\n"
                "→ `irislabs snowflake list-available` — liste les connexions demandables du tenant (pas les accès de l'app)\n"
                f"→ Erreur SDK : {raw}"
            )
        if "auth" in msg or "login" in msg or "unauthorized" in msg:
            return "❌ Authentification IrisLabs échouée. Vérifie IRIS_SDK_SECRET (peut-être expiré)."
        if "timeout" in msg:
            return "❌ Snowflake timeout — essaye une plage de dates plus courte."
        return f"❌ Erreur : {raw}"


# ── Health check ──────────────────────────────────────────────────────────────

def _find_irislabs_cli() -> str | None:
    """Locate the irislabs CLI binary, if present."""
    for candidate in [
        os.path.expanduser("~/.irislabs/bin/irislabs"),
        shutil.which("irislabs") if shutil.which("irislabs") else None,
    ]:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


# IrisLabs CLI login subcommands, tried in order. The CLI uses `auth login`;
# older builds used a bare `login`. We try the modern form first.
_IRIS_LOGIN_COMMANDS = [
    ["auth", "login"],
    ["login"],
]
_MANUAL_LOGIN_HINT = "~/.irislabs/bin/irislabs auth login"


@mcp.tool()
def iris_refresh() -> str:
    """Rafraîchit le token IrisLabs expiré en lançant `irislabs auth login` (ouvre le navigateur).

    Utilise cet outil quand un autre outil signale un token expiré. Après le login,
    le nouveau token est lu automatiquement — pas besoin de redémarrer Claude Code
    ni de copier le token à la main.
    """
    # Maybe it was already refreshed externally — re-read the live config first.
    _sync_token_from_iris_config()
    valid, msg = shared.check_token_expiry()
    if valid:
        return f"✅ Token déjà valide — {msg}"

    cli = _find_irislabs_cli()
    if not cli:
        return (
            "❌ CLI `irislabs` introuvable.\n"
            "Lance manuellement dans le terminal de ton Mac :\n"
            f"```\n{_MANUAL_LOGIN_HINT}\n```\n"
            "Puis relance ta requête (le token sera lu automatiquement)."
        )

    last_detail = ""
    for sub in _IRIS_LOGIN_COMMANDS:
        try:
            proc = subprocess.run([cli, *sub], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            # Login flow is open in the browser but didn't return in time.
            _sync_token_from_iris_config()
            valid, msg = shared.check_token_expiry()
            if valid:
                return f"✅ Token rafraîchi — {msg}"
            return (
                "⏳ La page de connexion est ouverte dans ton navigateur mais le login "
                "n'a pas terminé à temps. Complète-le, puis relance ta requête — le "
                "nouveau token sera lu automatiquement."
            )
        except Exception as e:
            last_detail = str(e)
            continue

        # Did this command produce a valid token?
        _sync_token_from_iris_config()
        valid, msg = shared.check_token_expiry()
        if valid:
            return f"✅ Token rafraîchi (`irislabs {' '.join(sub)}`) — {msg}"

        detail = (proc.stderr or proc.stdout or "").strip()
        # If the subcommand isn't recognized, try the next form; otherwise remember it.
        if "unknown command" in detail.lower() or "unknown subcommand" in detail.lower():
            last_detail = detail
            continue
        last_detail = detail
        # A recognized command that ran but didn't yield a valid token — stop trying others.
        break

    return (
        "❌ Le refresh n'a pas produit de token valide.\n"
        + (f"Sortie CLI : {last_detail}\n" if last_detail else "")
        + f"Lance manuellement : `{_MANUAL_LOGIN_HINT}`"
    )


@mcp.tool()
def iris_ping() -> str:
    """Full health check: SDK, token, config, and a SELECT 1 probe per Snowflake binding. Run this first if tools seem broken."""
    # Pick up any token refreshed since startup.
    _sync_token_from_iris_config()
    lines = ["## IRIS Health Check\n"]

    # Credentials source
    if _CREDS_SOURCE and _CREDS_HAS_TOKEN:
        lines.append(f"✅ Token source : SDK secret (fichier `{_CREDS_SOURCE}`) — auth app-specific")
    elif _IRIS_CONFIG_SOURCE:
        lines.append(
            f"⚠️  Token source : CLI JWT (fallback) `{_IRIS_CONFIG_SOURCE}`\n"
            "   → Le JWT CLI contient resource_id='1' (racine tenant) — IRISLABS_APP_ID\n"
            "     du credentials file sera ignoré si le SDK l'override.\n"
            "   → Recommandé : ajouter IRIS_SDK_SECRET (opaque SDK secret) dans\n"
            "     `~/Documents/Claude/.snowflake-dac-credentials.json`"
        )
    elif _CREDS_SOURCE:
        lines.append(f"📁 Credentials source : fichier `{_CREDS_SOURCE}` (sans SDK secret)")
    else:
        lines.append("📁 Credentials source : variables d'environnement (userConfig ou .env)")

    if SDK_FOUND:
        lines.append(f"✅ SDK : `{SDK_FOUND}`")
    else:
        lines.append(
            "❌ SDK IrisLabs introuvable\n"
            "   → Ajouter `IRISLABS_SDK_PATH` dans `~/.snowflake-dac-credentials.json`\n"
            "   → ou copier le SDK dans `~/mnt/Documents--Claude/.irislabs/sdk/`"
        )

    secret = os.environ.get("IRIS_SDK_SECRET")
    if secret:
        tok_valid, tok_msg = shared.check_token_expiry()
        icon = "✅" if tok_valid else "❌"
        lines.append(f"{icon} Token : {tok_msg}")
        if not tok_valid:
            lines.append("   → Appelle l'outil `iris_refresh` pour rafraîchir (ouvre le navigateur).")
    else:
        lines.append(
            "❌ IRIS_SDK_SECRET non configuré\n"
            "   → Appelle `iris_refresh`, ou crée `~/Documents/Claude/.snowflake-dac-credentials.json`"
        )

    cp_url = os.environ.get("IRIS_CONTROL_PLANE_URL", "")
    lines.append(f"{'✅' if cp_url else '❌'} IRIS_CONTROL_PLANE_URL : {cp_url or 'non configuré'}")

    app_id = os.environ.get("IRISLABS_APP_ID", "").strip()
    if not app_id:
        lines.append("❌ IRISLABS_APP_ID : non configuré")
    elif app_id == "1":
        lines.append(
            "⚠️  IRISLABS_APP_ID : '1' — valeur incorrecte (ID racine du tenant, pas un App GUID)\n"
            "   → Utilise le GUID de ton app (ex: b5d26977-481a-4f61-bf7c-b2f8cedf47fe)\n"
            "   → Pour lister tes apps : `irislabs app list`"
        )
    else:
        lines.append(f"✅ IRISLABS_APP_ID : {app_id}")

    app_id_ok = bool(app_id and app_id != "1")
    config_ok = bool(SDK_FOUND and secret and (not secret or shared.check_token_expiry()[0]) and cp_url and app_id_ok)

    # Sondes bindings — SELECT 1 par client, coût warehouse nul. C'est la seule
    # façon de tenir la promesse « run this first if tools seem broken » : la
    # config peut être 100% valide alors qu'un binding est mal nommé ou non
    # accordé (cause réelle de 2 mois de panne MNP). Non bloquant : un binding
    # KO n'empêche pas le rapport sur l'autre.
    bindings_ok = True
    if config_ok:
        lines.append("")
        for label, binding in (("Allstate", shared.ALLSTATE_BINDING), ("MNP", shared.MNP_BINDING)):
            try:
                shared.run_query("SELECT 1 AS ok", binding)
                lines.append(f"✅ Binding {label} (`{binding}`) : accessible")
            except Exception as e:
                bindings_ok = False
                lines.append(
                    f"❌ Binding {label} (`{binding}`) : {e}\n"
                    "   → `irislabs snowflake bindings` depuis le répertoire de l'app (seule source fiable)"
                )
    else:
        lines.append("\n⏭️  Sondes bindings sautées — corrige d'abord la configuration ci-dessus")

    all_ok = config_ok and bindings_ok
    if all_ok:
        lines.append("\n✅ Configuration OK — bindings vérifiés, prêt pour les requêtes Snowflake")
    elif config_ok:
        lines.append("\n⚠️  Configuration OK mais au moins un binding est inaccessible — voir ci-dessus")
    else:
        lines.append("\n❌ Configuration incomplète — voir les erreurs ci-dessus")

    if not all_ok and not _CREDS_SOURCE:
        lines.append(
            "\n💡 **Cowork / VM** : crée ce fichier sur ton Mac :\n"
            "```\n"
            "cat > ~/Documents/Claude/.snowflake-dac-credentials.json << 'EOF'\n"
            "{\n"
            '  "IRIS_CONTROL_PLANE_URL": "https://irislabs.dacgroup.com",\n'
            '  "IRISLABS_APP_ID": "<GUID-de-ton-app-irislabs>",\n'
            '  "IRIS_SDK_SECRET": "<opaque-sdk-secret>",\n'
            '  "IRISLABS_SDK_PATH": "/chemin/vers/.irislabs/sdk"\n'
            "}\n"
            "EOF\n"
            "chmod 600 ~/Documents/Claude/.snowflake-dac-credentials.json\n"
            "```\n"
            "→ SDK secret : `irislabs apps secret regenerate --env prod --app <GUID>`"
        )
    return "\n".join(lines)


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
