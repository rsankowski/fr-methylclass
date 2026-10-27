#!/usr/bin/env bash
# Build (and optionally push) the pipeline images.
#   containers/build.sh                    # build all
#   containers/build.sh crossnn sturgeon   # only some
#   PUSH=1 containers/build.sh hts align report
#
# Public images (hts, align, report) are tagged ${REGISTRY}/<name>:${TAG}
# (default ghcr.io/rsankowski) and may be pushed.
# Classifier images (crossnn, methylyzr, sturgeon, lamprey) contain code whose
# licences forbid redistribution. They are tagged ${RESTRICTED_REGISTRY}/<name>:${TAG}
# (default methylclass, matching --restricted_registry) and are never pushed.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${REGISTRY:-ghcr.io/rsankowski}"
RESTRICTED_REGISTRY="${RESTRICTED_REGISTRY:-methylclass}"
TAG="${TAG:-1.0.0}"
RESTRICTED=" crossnn methylyzr sturgeon lamprey "
IMAGES=("$@")
[ ${#IMAGES[@]} -gt 0 ] || IMAGES=(hts align report crossnn methylyzr sturgeon lamprey)
for name in "${IMAGES[@]}"; do
    if [[ "$RESTRICTED" == *" $name "* ]]; then
        image="${RESTRICTED_REGISTRY}/${name}:${TAG}"
        echo ">> building ${image} (restricted licence: local only, not pushed)"
        docker build -t "${image}" "${DIR}/${name}"
    else
        image="${REGISTRY}/${name}:${TAG}"
        echo ">> building ${image}"
        docker build -t "${image}" "${DIR}/${name}"
        if [ "${PUSH:-0}" = 1 ]; then docker push "${image}"; fi
    fi
done
