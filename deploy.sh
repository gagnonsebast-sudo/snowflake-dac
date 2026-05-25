#!/bin/bash
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$HOME/.config/snowflake-dac"

echo "🚀 Déploiement du plugin Snowflake DAC..."

# Mettre à jour depuis GitHub
echo "🔄 Mise à jour depuis GitHub..."
git -C "$REPO_DIR" pull origin main
echo "✅ Code à jour"

# Créer le dossier de déploiement si nécessaire
mkdir -p "$DEPLOY_DIR"

# Copier les fichiers du serveur
cp -r "$REPO_DIR/server.py"  "$DEPLOY_DIR/server.py"
cp -r "$REPO_DIR/tools"      "$DEPLOY_DIR/tools"
mkdir -p "$DEPLOY_DIR/scheduled"
cp -r "$REPO_DIR/scheduled/anomaly_check.py" "$DEPLOY_DIR/scheduled/anomaly_check.py"
echo "✅ Serveur copié vers $DEPLOY_DIR"

# Localiser le SDK IrisLabs
SDK_CANDIDATES=(
    "$REPO_DIR/../report-generator/.irislabs/sdk"
    "$HOME/Documents/Claude/Projects/IRIS/report-generator/.irislabs/sdk"
    "$HOME/iris/report-generator/.irislabs/sdk"
    "$HOME/report-generator/.irislabs/sdk"
    "$HOME/IRIS/report-generator/.irislabs/sdk"
    "$HOME/Desktop/Claude/Allstate/iris-app/.irislabs/sdk"
)

SDK_PATH=""
for candidate in "${SDK_CANDIDATES[@]}"; do
    if [ -d "$candidate" ]; then
        SDK_PATH="$(cd "$candidate" && pwd)"
        break
    fi
done

if [ -n "$SDK_PATH" ]; then
    # Créer un lien symbolique sdk/ dans le dossier de déploiement
    rm -rf "$DEPLOY_DIR/sdk"
    ln -s "$SDK_PATH" "$DEPLOY_DIR/sdk"
    echo "✅ SDK IrisLabs lié : $SDK_PATH"
else
    echo ""
    echo "⚠️  SDK IrisLabs introuvable aux emplacements standards."
    echo "   Lance manuellement :"
    echo "   ln -s /chemin/vers/report-generator/.irislabs/sdk $DEPLOY_DIR/sdk"
fi

echo ""
echo "🎉 Déploiement terminé. Redémarre Cowork pour charger la nouvelle version."
