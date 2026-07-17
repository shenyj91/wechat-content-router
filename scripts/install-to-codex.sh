#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC="$REPO_ROOT/skills/wechat-content-router"
DST="$HOME/.codex/skills/wechat-content-router"

mkdir -p "$HOME/.codex/skills"
rm -rf "$DST"
cp -R "$SRC" "$DST"

echo "Installed to: $DST"
