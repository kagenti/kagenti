#!/bin/bash
# bob-install.sh — Install bobshell without npm dependency resolution.
# Works around OpenShell proxy blocking %2f in URLs (scoped packages).
# Downloads tarballs directly with literal slashes (which the proxy allows).
set -e
NPM_GLOBAL="/sandbox/.npm-global"
BOB_DIR="$NPM_GLOBAL/lib/node_modules/bobshell"
TMP="/tmp/bob-install-$$"
mkdir -p "$TMP" "$NPM_GLOBAL/bin" "$NPM_GLOBAL/lib/node_modules"
BOB_VERSION=$(curl -fsSL "https://s3.us-south.cloud-object-storage.appdomain.cloud/bob-shell/bobshell-version.txt" 2>/dev/null || echo "1.0.4")
BOB_VERSION=$(echo "$BOB_VERSION" | tr -d "[:space:]")
echo "  Version: $BOB_VERSION"
echo "  Downloading bobshell..."
curl -fsSL "https://s3.us-south.cloud-object-storage.appdomain.cloud/bob-shell/bobshell-${BOB_VERSION}.tgz" -o "$TMP/bobshell.tgz"
mkdir -p "$BOB_DIR"
tar xzf "$TMP/bobshell.tgz" -C "$BOB_DIR" --strip-components=1
echo "  Downloading dependencies..."
mkdir -p "$BOB_DIR/node_modules"
curl -fsSL "https://registry.npmjs.org/pdf-parse/-/pdf-parse-2.4.5.tgz" -o "$TMP/pdf-parse.tgz"
mkdir -p "$BOB_DIR/node_modules/pdf-parse"
tar xzf "$TMP/pdf-parse.tgz" -C "$BOB_DIR/node_modules/pdf-parse" --strip-components=1
PDFJS_VER=$(node -e "try{console.log(require('$BOB_DIR/node_modules/pdf-parse/package.json').dependencies['pdfjs-dist']||'5.4.296')}catch(e){console.log('5.4.296')}")
echo "  pdfjs-dist version: $PDFJS_VER"
curl -fsSL "https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-${PDFJS_VER}.tgz" -o "$TMP/pdfjs-dist.tgz" 2>/dev/null || true
if [ -f "$TMP/pdfjs-dist.tgz" ] && [ -s "$TMP/pdfjs-dist.tgz" ]; then
  mkdir -p "$BOB_DIR/node_modules/pdfjs-dist"
  tar xzf "$TMP/pdfjs-dist.tgz" -C "$BOB_DIR/node_modules/pdfjs-dist" --strip-components=1
fi
curl -fsSL "https://registry.npmjs.org/@napi-rs/canvas/-/canvas-0.1.80.tgz" -o "$TMP/napi-canvas.tgz" 2>/dev/null || true
if [ -f "$TMP/napi-canvas.tgz" ] && [ -s "$TMP/napi-canvas.tgz" ]; then
  mkdir -p "$BOB_DIR/node_modules/@napi-rs/canvas"
  tar xzf "$TMP/napi-canvas.tgz" -C "$BOB_DIR/node_modules/@napi-rs/canvas" --strip-components=1
fi
BIN_ENTRY=$(node -e "try{const p=require('$BOB_DIR/package.json');const b=typeof p.bin==='string'?p.bin:p.bin&&p.bin.bob||p.bin&&Object.values(p.bin)[0]||'bin/bob.js';console.log(b)}catch(e){console.log('bin/bob.js')}")
echo "  Bin entry: $BIN_ENTRY"
ln -sf "$BOB_DIR/$BIN_ENTRY" "$NPM_GLOBAL/bin/bob"
chmod +x "$NPM_GLOBAL/bin/bob" "$BOB_DIR/$BIN_ENTRY" 2>/dev/null || true
rm -rf "$TMP"
echo "  Done."
