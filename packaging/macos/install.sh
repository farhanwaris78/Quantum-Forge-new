#!/usr/bin/env bash
# Thin macOS convenience wrapper around the shared portable installer.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -x "$SCRIPT_DIR/../unix/install.sh" ]]; then
    exec "$SCRIPT_DIR/../unix/install.sh" "$@"
fi
if [[ -x "$SCRIPT_DIR/install.sh" && "$SCRIPT_DIR" != *"/packaging/macos" ]]; then
    # Inside a released portable bundle, install.sh is already at the root.
    exec "$SCRIPT_DIR/install.sh" "$@"
fi
echo "Could not locate the portable installer." >&2
exit 2
