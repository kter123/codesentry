#!/usr/bin/env bash
# Install optional CodeSentry tool-gateway binaries.
# Safe defaults: only Python packages into the active venv; external binaries are opt-in.
set -euo pipefail

echo "[CodeSentry] install Bandit/Safety into current Python env"
uv pip install bandit safety

if [[ "${CODESENTRY_INSTALL_EXTERNAL:-0}" == "1" ]]; then
  echo "[CodeSentry] installing external binaries (requires Homebrew + network)"
  brew install gitleaks osv-scanner || true
fi

echo "[CodeSentry] done"
