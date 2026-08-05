#!/usr/bin/env bash
# Verify release artifacts against SHA256SUMS in the current directory.
set -euo pipefail
[[ -f SHA256SUMS ]] || { echo "SHA256SUMS is missing." >&2; exit 2; }
if command -v sha256sum >/dev/null; then
    sha256sum --check --strict SHA256SUMS
elif command -v shasum >/dev/null; then
    shasum -a 256 -c SHA256SUMS
else
    echo "Neither sha256sum nor shasum is available." >&2
    exit 2
fi
