#!/usr/bin/env bash
# Build an Arch Linux pacman package from a platform-matched portable archive.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
ARCHIVE="${1:?Usage: packaging/arch/build-package.sh <portable.tar.gz>}"
ARCHIVE="$(CDPATH= cd -- "$(dirname -- "$ARCHIVE")" && pwd -P)/$(basename -- "$ARCHIVE")"
[[ -f "$ARCHIVE" ]] || { echo "Archive not found: $ARCHIVE" >&2; exit 2; }
command -v makepkg >/dev/null || { echo "makepkg is required (run this on Arch Linux)." >&2; exit 2; }
VERSION="$(basename "$ARCHIVE" | sed -E 's/^QuantumForge-([0-9][0-9A-Za-z.-]*)-linux-(x64|arm64)\.tar\.gz$/\1/')"
[[ "$VERSION" != "$(basename "$ARCHIVE")" ]] || { echo "Unexpected archive name." >&2; exit 2; }
SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
WORK="$ROOT/target/arch-package"
rm -rf "$WORK"; mkdir -p "$WORK"
cp "$ROOT/packaging/arch/PKGBUILD" "$WORK/PKGBUILD"
cd "$WORK"
QF_ARCHIVE="$ARCHIVE" QF_VERSION="$VERSION" QF_SHA256="$SHA" makepkg --clean --force --noconfirm
mkdir -p "$ROOT/target/release"
cp ./*.pkg.tar.zst "$ROOT/target/release/"
find "$ROOT/target/release" -maxdepth 1 -name '*.pkg.tar.zst' -print
