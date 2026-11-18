#!/usr/bin/env bash
# Fetch the classifier models / data into one folder, then run the pipeline
# with --assets_dir <folder>.
#
#   scripts/download_assets.sh /data/methylclass-assets [crossnn methylyzr sturgeon lamprey]
#
# Layout written (what main.nf looks for under --assets_dir):
#   crossnn/Capper_et_al_NN.pkl  crossnn/pancan_devel_v5i_NN.pkl
#   methylyzr/EPIC_CpGannotation.bed  methylyzr/betas_mean.feather
#   methylyzr/W_RELIEF.feather  methylyzr/class_priors.csv
#   sturgeon/cns-v2.5.zip      (Sturgeon V2; keep the file name)
#   lamprey/model/            (HuggingFace snapshot of tachterberg/Lamprey, 6.8 GB)
#
# Needs: git, git-lfs, curl, unzip; python3 + huggingface_hub for Lamprey.
# Check each tool's licence before use. Sizes: crossNN 0.35 GB, MethyLYZR 0.65 GB,
# Sturgeon V2 3.4 GB, Lamprey 6.8 GB.
set -euo pipefail

OUT="${1:?usage: download_assets.sh <outdir> [crossnn methylyzr sturgeon lamprey]}"
shift
WANT=("$@")
[ ${#WANT[@]} -gt 0 ] || WANT=(crossnn methylyzr sturgeon lamprey)
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

CROSSNN_COMMIT=26e4db9bf9c16711aa834f2e944a84a920baccc7
METHYLYZR_COMMIT=f78855e6f00e77896aa7e9893ef4aa767f7bf212
LAMPREY_REVISION=6167d763c877eb9c19a9ab64b0e8cb4557423cd4

crossnn() {
    mkdir -p "$OUT/crossnn"
    git clone -q https://gitlab.com/euskirchen-lab/crossnn.git "$TMP/crossnn"
    git -C "$TMP/crossnn" checkout -q "$CROSSNN_COMMIT"
    git -C "$TMP/crossnn" lfs pull
    cp "$TMP/crossnn/models/"*.pkl "$OUT/crossnn/"
}

methylyzr() {
    mkdir -p "$OUT/methylyzr"
    curl -fsSL -o "$OUT/methylyzr/EPIC_CpGannotation.bed" \
        "https://raw.githubusercontent.com/marasteiger/MethyLYZR/${METHYLYZR_COMMIT}/data/EPIC_CpGannotation.bed"
    curl -fsSL -o "$OUT/methylyzr/class_priors.csv" \
        "https://raw.githubusercontent.com/marasteiger/MethyLYZR/${METHYLYZR_COMMIT}/model/class_priors.csv"
    # centroids + weights: MPI-MG Nextcloud share named in the MethyLYZR README
    curl -fsSL -o "$TMP/methylyzr.zip" \
        "https://nc.molgen.mpg.de/cloud/index.php/s/sJJds3gfsmba5K2/download"
    unzip -q -o -j "$TMP/methylyzr.zip" '*betas_mean.feather' '*W_RELIEF.feather' -d "$OUT/methylyzr" \
        || { echo "MethyLYZR: unexpected archive layout - unpack $TMP/methylyzr.zip into $OUT/methylyzr by hand" >&2; return 1; }
}

sturgeon() {
    mkdir -p "$OUT/sturgeon"
    # Sturgeon V2 cns-v2.5 model, Zenodo record 22899108
    curl -fsSL -o "$OUT/sturgeon/cns-v2.5.zip" \
        "https://zenodo.org/records/22899108/files/cns-v2.5.zip"
    echo "9e45b5d8788b7fecce1d1d4293e32fc9  $OUT/sturgeon/cns-v2.5.zip" | md5sum -c -
}

lamprey() {
    mkdir -p "$OUT/lamprey"
    python3 - "$OUT/lamprey/model" "$LAMPREY_REVISION" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download("tachterberg/Lamprey", revision=sys.argv[2], local_dir=sys.argv[1])
PY
}

for t in "${WANT[@]}"; do
    echo ">> $t"
    "$t"
done
echo "Assets in $OUT  ->  nextflow run main.nf --assets_dir $OUT ..."
