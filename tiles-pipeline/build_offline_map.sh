#!/bin/bash
# ==========================================================================
# Génère des tuiles vectorielles offline (.mbtiles) pour une zone donnée,
# à partir de données OpenStreetMap 100% libres (Geofabrik).
#
# Légal et illimité : on télécharge un extrait de données brutes (autorisé
# en bulk par Geofabrik), puis on génère nous-mêmes les tuiles avec
# Planetiler (pas de scraping de serveur de tuiles tiers).
#
# Usage : ./build_offline_map.sh <region> [memory] [bounds] [output_name]
# Exemple : ./build_offline_map.sh spain
#           ./build_offline_map.sh france
#           ./build_offline_map.sh europe   (⚠️ ~32 Go de PBF, long)
#           ./build_offline_map.sh europe/spain 4g "2.0,41.3,2.3,41.5" chantier-barcelone
#
# <region> peut être un nom simple ("spain" => europe/spain, pour rester
# compatible avec les usages existants) ou un chemin Geofabrik complet
# ("north-america/us/california").
#
# [bounds] (optionnel) : "west,south,east,north" -- limite la sortie à une
# emprise personnalisée (dessinée dans la page Offline Maps) au lieu de
# générer toute la région. Le fichier .osm.pbf de la région est quand
# même téléchargé une fois (Geofabrik ne propose pas d'extraits sur
# mesure), mais le .mbtiles généré ne couvre que cette emprise.
#
# [output_name] (optionnel) : nom du fichier .mbtiles de sortie, utile
# pour ne pas écraser le fichier région entière quand [bounds] est fourni.
#
# Régions disponibles : voir https://download.geofabrik.de
# ==========================================================================

set -e

REGION="${1:-spain}"
DATA_DIR="./data"
MEMORY="${2:-4g}"   # ajuster selon la RAM disponible (ex: 8g, 16g)
BOUNDS="${3:-}"
OUTPUT_NAME="${4:-}"

# Reste compatible avec les appels existants ("spain") tout en acceptant
# un chemin Geofabrik complet ("europe/spain", "north-america/us/california").
if [[ "$REGION" == */* ]]; then
    REGION_PATH="$REGION"
else
    REGION_PATH="europe/${REGION}"
fi
REGION_BASENAME="$(basename "$REGION_PATH")"

PBF_URL="https://download.geofabrik.de/${REGION_PATH}-latest.osm.pbf"
PBF_FILE="${DATA_DIR}/${REGION_BASENAME}-latest.osm.pbf"
OUTPUT_MBTILES="${DATA_DIR}/${OUTPUT_NAME:-$REGION_BASENAME}.mbtiles"
PLANETILER_JAR="./planetiler.jar"
PLANETILER_VERSION="0.9.0"

mkdir -p "$DATA_DIR"

echo "=== Étape 1/3 : Téléchargement de Planetiler ==="
if [ ! -f "$PLANETILER_JAR" ]; then
    curl -L -o "$PLANETILER_JAR" \
        "https://github.com/onthegomap/planetiler/releases/download/v${PLANETILER_VERSION}/planetiler.jar"
else
    echo "Planetiler déjà présent, skip."
fi

echo ""
echo "=== Étape 2/3 : Téléchargement des données OSM pour '${REGION_PATH}' ==="
echo "Source : ${PBF_URL}"

download_with_retry() {
    local url="$1"
    local dest="$2"
    local max_attempts=3
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        echo "Tentative ${attempt}/${max_attempts}..."
        if curl -L --fail --retry 2 --retry-delay 5 --connect-timeout 30 -o "$dest" "$url"; then
            # Vérifie que le fichier téléchargé a une taille raisonnable (>1 Mo)
            # pour détecter les téléchargements tronqués ou les pages d'erreur HTML
            size=$(stat -c%s "$dest" 2>/dev/null || stat -f%z "$dest" 2>/dev/null || echo 0)
            if [ "$size" -gt 1000000 ]; then
                return 0
            else
                echo "Fichier téléchargé trop petit (${size} octets), probablement une erreur serveur."
                rm -f "$dest"
            fi
        else
            echo "Échec du téléchargement (tentative ${attempt})."
        fi
        attempt=$((attempt + 1))
        [ $attempt -le $max_attempts ] && sleep 10
    done

    echo "ERREUR : impossible de télécharger ${url} après ${max_attempts} tentatives."
    echo "Le serveur Geofabrik est peut-être temporairement indisponible — réessaie dans quelques minutes."
    exit 1
}

if [ ! -f "$PBF_FILE" ]; then
    download_with_retry "$PBF_URL" "$PBF_FILE"
else
    echo "Fichier déjà présent, skip. (supprimer $PBF_FILE pour forcer le ré-téléchargement)"
fi

echo ""
echo "=== Étape 3/3 : Génération des tuiles vectorielles (.mbtiles) ==="
echo "Mémoire allouée : ${MEMORY}"
if [ -n "$BOUNDS" ]; then
    echo "Emprise personnalisée : ${BOUNDS}"
fi
echo "(Planetiler va aussi télécharger ~200 Mo de données auxiliaires :"
echo " polygones d'eau, lignes de côte, Natural Earth — une seule fois,"
echo " réutilisées pour toutes les régions suivantes)"

PLANETILER_ARGS=(--osm-path="$PBF_FILE" --output="$OUTPUT_MBTILES" --download --force)
if [ -n "$BOUNDS" ]; then
    PLANETILER_ARGS+=(--bounds="$BOUNDS")
fi

java -Xmx${MEMORY} -jar "$PLANETILER_JAR" "${PLANETILER_ARGS[@]}"

echo ""
echo "✅ Terminé !"
echo "Fichier généré : $(realpath "$OUTPUT_MBTILES")"
echo "Taille : $(du -h "$OUTPUT_MBTILES" | cut -f1)"
echo ""
echo "Ce fichier est prêt à être utilisé depuis la page Offline Maps de"
echo "l'application (bouton \"Use offline\"), ou servi manuellement via"
echo "serve_tiles.py."
