#!/usr/bin/env bash
# Build (and optionally push) the pipeline images.
#   containers/build.sh                    # build all as ghcr.io/rsankowski/<name>:1.0.0
#   REGISTRY=ghcr.io/me PUSH=1 containers/build.sh
#   containers/build.sh hts report         # only some
# Singularity/Apptainer: push to a registry, then run with
#   -profile singularity --container_registry <registry>
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/rsankowski}"
TAG="${TAG:-1.0.0}"
IMAGES=("$@")
[ ${#IMAGES[@]} -gt 0 ] || IMAGES=(hts align crossnn methylyzr sturgeon lamprey report)
for name in "${IMAGES[@]}"; do
    echo ">> building ${REGISTRY}/${name}:${TAG}"
    docker build -t "${REGISTRY}/${name}:${TAG}" "${DIR}/${name}"
    if [ "${PUSH:-0}" = 1 ]; then docker push "${REGISTRY}/${name}:${TAG}"; fi
done
