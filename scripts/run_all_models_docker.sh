#!/bin/bash
set -euo pipefail

INPUT_FOLD=$1
CANCER=$2
CONVERT_PATH=$3
TMP_LOG="${INPUT_FOLD}/tmp_run.log"

# 1. BASE PATHS
BASE_PATH="${HOST_PWD:-$(cd "$(dirname "$0")/.." && pwd)}/utilities/gdan-tmp-models"
cd "$BASE_PATH"

# Il volume condiviso
RELATIVE_SHARED_DIR="shared_data"
SHARED_DIR="${BASE_PATH}/${RELATIVE_SHARED_DIR}"

echo ">>> Working Directory: $(pwd)"

# Prep volume
mkdir -p "${SHARED_DIR}/tmp" "${SHARED_DIR}/data"
rm -rf "${SHARED_DIR}/tmp"/* "${SHARED_DIR}/data"/*
mkdir -p "${INPUT_FOLD}"
: > "${TMP_LOG}"

# 2. PRE-PROCESSING
echo ">>> Step 1: Conversion..."
python3 tools/convert.py --data "${INPUT_FOLD}/tmp_data.txt" --out "${SHARED_DIR}/data/${CANCER}_GEXP.tsv" --cancer "${CANCER}" --conversion_file "${CONVERT_PATH}"

echo ">>> Step 2: Transformation..."
bash tools/run_transform.sh "${SHARED_DIR}/data/${CANCER}_GEXP.tsv" ${CANCER}

# Spostiamo il file nel volume
ORIGIN_FILE="user-transformed-data/transformed-data.tsv"
DEST_FILE="${SHARED_DIR}/data/transformed-data.tsv"

if [ -f "$ORIGIN_FILE" ]; then
    mv "$ORIGIN_FILE" "$DEST_FILE"
else
    echo "ERRORE: $ORIGIN_FILE non trovato!"
    exit 1
fi

# 3. CLEANING
python3 tools/zero_floor.py -in "$DEST_FILE" -out "$DEST_FILE"
tr '\t' ',' < "$DEST_FILE" > "${SHARED_DIR}/data/transformed-data.csv"

# 4. PATH RELATIVO PER I MODELLI (Cruciale per evitare raddoppi)
# Usiamo questo percorso per create_jobs.py
RELATIVE_DATA_PATH="shared_data/data/transformed-data.tsv"

# 5. ESECUZIONE MODELLI
HOST_ARCH="$(uname -m)"
if [[ "${HOST_ARCH}" == "x86_64" ]]; then
    HOST_ARCH="amd64"
elif [[ "${HOST_ARCH}" == "aarch64" ]]; then
    HOST_ARCH="arm64"
fi

for MODEL in jadbio skgrid aklimate subscope cloudforest; do
    echo "------------------------------------------"
    echo ">>> Execution: $MODEL"
    echo ">>> Execution: $MODEL" >> "${TMP_LOG}"

    if [[ "$MODEL" == "aklimate" ]]; then
        case "${CANCER}" in
            ACC|PAAD|UVM)
                echo ">>> Skipping aklimate: no model available for ${CANCER}_GEXP."
                echo ">>> Skipping aklimate: no model available for ${CANCER}_GEXP." >> "${TMP_LOG}"
                continue
                ;;
        esac
    fi

    if [[ "$MODEL" == "cloudforest" ]]; then
        if [[ ! -d "${BASE_PATH}/cloudforest/data/models_cf" ]]; then
            echo ">>> Skipping cloudforest: models_cf directory not found."
            echo ">>> Skipping cloudforest: models_cf directory not found." >> "${TMP_LOG}"
            continue
        fi

        CF_ARCH="$(docker image inspect docker.synapse.org/syn29568296/cloudforest_all --format '{{.Architecture}}' 2>/dev/null || true)"
        if [[ -n "${CF_ARCH}" && "${CF_ARCH}" != "${HOST_ARCH}" ]]; then
            echo ">>> Skipping cloudforest: image architecture ${CF_ARCH} does not match host ${HOST_ARCH}."
            echo ">>> Skipping cloudforest: image architecture ${CF_ARCH} does not match host ${HOST_ARCH}." >> "${TMP_LOG}"
            continue
        fi
    fi
    
    # Passiamo RELATIVE_DATA_PATH invece di DEST_FILE
    if bash RUN_MODEL.sh ${CANCER} GEXP ${MODEL} "$RELATIVE_DATA_PATH" >> "${TMP_LOG}" 2>&1; then
        :
    else
        exit_code=$?
        echo ">>> ERROR: ${MODEL} failed with exit code ${exit_code}" >> "${TMP_LOG}"
        exit 1
    fi
done

# 7. RECUPERO RISULTATI
echo "------------------------------------------"
echo ">>> Step 5: Moving Results..."
mkdir -p "${INPUT_FOLD}"

copy_if_exists() {
    local src="$1"
    local dst="$2"
    local label="$3"

    if [[ -f "$src" ]]; then
        cp -f "$src" "$dst"
        echo ">>> Copied ${label}: ${src} -> ${dst}"
    else
        echo ">>> Missing ${label}: ${src}"
    fi
}

copy_if_exists "aklimate/preds/${CANCER}_GEXP_predictions_for_transformed-data.tsv" "${INPUT_FOLD}/aklimate_preds.tsv" "aklimate prediction"
copy_if_exists "cloudforest/preds/${CANCER}_GEXP_cloudforest_preds.tsv" "${INPUT_FOLD}/cloudforest_preds.tsv" "cloudforest prediction"
copy_if_exists "cloudforest/preds/${CANCER}_GEXP_cloudforest_votes.vo" "${INPUT_FOLD}/cloudforest_votes.vo" "cloudforest votes"
copy_if_exists "jadbio/preds/${CANCER}_GEXP_jadbio_preds.csv" "${INPUT_FOLD}/jadbio_preds.csv" "jadbio prediction"
copy_if_exists "skgrid/preds/${CANCER}_GEXP_skgrid_preds.tsv" "${INPUT_FOLD}/skgrid_preds.tsv" "skgrid prediction"
copy_if_exists "subscope/preds/GEXP-subscope-results.txt" "${INPUT_FOLD}/subscope_results.txt" "subscope prediction"

find "${INPUT_FOLD}" -maxdepth 1 -type f | sort > "${INPUT_FOLD}/tmp_predictions_manifest.txt"

# 8. PULIZIA FINALE
echo ">>> Final Cleanup..."
echo ">>> Final Cleanup..." >> "${TMP_LOG}"
# rm -rf "${SHARED_DIR}/data"/* "${SHARED_DIR}/tmp"/* <-- Consiglio: commentalo per i primi test per debug
# rm -rf aklimate/preds/* cloudforest/preds/* jadbio/preds/* skgrid/preds/* subscope/preds/*

echo ">>> ALL PROCESSES COMPLETED!"
echo ">>> ALL PROCESSES COMPLETED!" >> "${TMP_LOG}"
