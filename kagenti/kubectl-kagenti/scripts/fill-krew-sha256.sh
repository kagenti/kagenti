#!/usr/bin/env bash
# Download release tarballs and print sha256 lines for pasting into deploy/krew/kagenti.yaml
set -euo pipefail
VERSION="${1:-v0.1.0}"
BASE="https://github.com/akram/kubectl-kagenti/releases/download/${VERSION}"
for pair in darwin/amd64 darwin/arm64 linux/amd64 linux/arm64 windows/amd64; do
  os="${pair%%/*}"
  arch="${pair##*/}"
  ext=tar.gz
  name="kubectl-kagenti_${VERSION}_${os}_${arch}.${ext}"
  url="${BASE}/${name}"
  echo "curl -sL '$url' | shasum -a 256   # ${os}_${arch}"
  curl -sL "$url" | shasum -a 256
done
