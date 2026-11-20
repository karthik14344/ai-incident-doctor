#!/bin/sh
# Build the agent team's images from AGAI's own checkout.
#
#   deploy/agai/build.sh [AGAI_DIR]
#
# 1. aid/agai-base:<AGAI commit>  - AGAI's own Dockerfile, untouched
# 2. aid/agai:<AGAI commit>       - deploy/agai/Dockerfile on top (our test deps)
#
# Prints the tag; put it in .env as AGAI_IMAGE_TAG so compose runs that image.
set -eu
AGAI_DIR=${1:-${AGAI_DIR:-./AGAI}}
PREFIX=${IMAGE_PREFIX:-aid}
TAG=$(git -C "$AGAI_DIR" rev-parse --short HEAD)
docker build -q -t "$PREFIX/agai-base:$TAG" "$AGAI_DIR" >/dev/null
docker build -q --build-arg "AGAI_BASE=$PREFIX/agai-base:$TAG" -t "$PREFIX/agai:$TAG" \
  "$(dirname "$0")" >/dev/null
echo "$TAG"
