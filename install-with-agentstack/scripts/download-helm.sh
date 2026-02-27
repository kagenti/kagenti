#!/bin/bash
set -euo pipefail

# Download Helm and place it at ./bin/helm-<ver>/helm.
# Detects OS and architecture automatically.

HELM_VERSION="${1:-v3.19.5}"

# Detect OS
case "$(uname -s)" in
  Darwin) OS="darwin" ;;
  Linux)  OS="linux" ;;
  *)      echo "❌ Unsupported OS: $(uname -s)"; exit 1 ;;
esac

# Detect architecture
case "$(uname -m)" in
  x86_64)       ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *)            echo "❌ Unsupported architecture: $(uname -m)"; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INSTALL_DIR="${REPO_ROOT}/bin/helm-${HELM_VERSION}"

# Skip if already downloaded
if [[ -x "${INSTALL_DIR}/helm" ]]; then
  echo "✅ Helm ${HELM_VERSION} already exists at ${INSTALL_DIR}/helm"
  exit 0
fi

TARBALL="helm-${HELM_VERSION}-${OS}-${ARCH}.tar.gz"
URL="https://get.helm.sh/${TARBALL}"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "⬇️  Downloading Helm ${HELM_VERSION} (${OS}/${ARCH})..."
curl -fSL "$URL" -o "${TMPDIR}/${TARBALL}"

echo "📦 Extracting..."
tar -xzf "${TMPDIR}/${TARBALL}" -C "${TMPDIR}"

mkdir -p "${INSTALL_DIR}"
mv "${TMPDIR}/${OS}-${ARCH}/helm" "${INSTALL_DIR}/helm"
chmod +x "${INSTALL_DIR}/helm"

echo "✅ Helm ${HELM_VERSION} installed at ${INSTALL_DIR}/helm"
