#!/usr/bin/env bash
# Atomic, unprivileged installer for a downloaded QuantumForge portable bundle.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "$SCRIPT_DIR/VERSION" ]]; then
    SOURCE_ROOT="$SCRIPT_DIR"                 # top-level convenience copy
else
    SOURCE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"  # management/install.sh
fi
INSTALL_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/quantumforge"
BIN_DIR="$HOME/.local/bin"
YES=0

usage() {
    cat <<'EOF'
Usage: ./management/install.sh [OPTIONS]

Options:
  --prefix DIR   application root (default: $XDG_DATA_HOME/quantumforge)
  --bin-dir DIR  command directory (default: ~/.local/bin)
  --yes          non-interactive mode
  --help         show this help

The installer never requires sudo and does not modify shell startup files.
Existing ~/.quantumforge projects, settings, pseudopotentials, and logs are not touched.
EOF
}

while (($#)); do
    case "$1" in
        --prefix) INSTALL_ROOT="${2:?--prefix needs a directory}"; shift 2 ;;
        --bin-dir) BIN_DIR="${2:?--bin-dir needs a directory}"; shift 2 ;;
        --yes) YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown installer option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

VERSION_FILE="$SOURCE_ROOT/VERSION"
[[ -f "$VERSION_FILE" ]] || { echo "Missing VERSION in bundle." >&2; exit 3; }
VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || {
    echo "Unsafe or invalid bundle version: $VERSION" >&2; exit 3;
}
[[ -f "$SOURCE_ROOT/app/quantumforge.jar" && -x "$SOURCE_ROOT/bin/quantumforge" ]] || {
    echo "Bundle is incomplete; refusing to install." >&2; exit 3;
}

INSTALL_ROOT="$(mkdir -p "$INSTALL_ROOT" && CDPATH= cd -- "$INSTALL_ROOT" && pwd -P)"
mkdir -p "$INSTALL_ROOT/versions" "$BIN_DIR"
chmod 700 "$INSTALL_ROOT" 2>/dev/null || true

TARGET="$INSTALL_ROOT/versions/$VERSION"
STAGE="$INSTALL_ROOT/versions/.${VERSION}.staging.$$"
BACKUP="$INSTALL_ROOT/versions/.${VERSION}.backup.$$"
CURRENT_TMP="$INSTALL_ROOT/.current.$$"
LINK_TMP="$BIN_DIR/.quantumforge.$$"
cleanup() {
    rm -rf -- "$STAGE" "$CURRENT_TMP" "$LINK_TMP"
    if [[ -d "$BACKUP" && ! -d "$TARGET" ]]; then mv -- "$BACKUP" "$TARGET"; fi
}
trap cleanup EXIT HUP INT TERM

# The distributed bundle contains no symlinks. Reject unexpected links so a
# modified archive cannot make cp read outside the extraction directory.
if find "$SOURCE_ROOT" -type l -print -quit | grep -q .; then
    echo "Bundle contains an unexpected symbolic link; refusing to install." >&2
    exit 4
fi

mkdir -m 700 "$STAGE"
cp -a "$SOURCE_ROOT/." "$STAGE/"
printf 'version=%s\ninstalled_at=%s\nbin_dir=%s\n' \
    "$VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BIN_DIR" > "$STAGE/INSTALL_RECEIPT"

if [[ -d "$TARGET" ]]; then mv -- "$TARGET" "$BACKUP"; fi
mv -- "$STAGE" "$TARGET"
rm -rf -- "$BACKUP"

ln -s "versions/$VERSION" "$CURRENT_TMP"
# The destination of this move is a symlink to a DIRECTORY. Plain `mv` follows
# such symlinks on both GNU and BSD, which parks the new pointer INSIDE the old
# version while reporting success: an update would install but never activate.
# GNU mv -fT replaces the symlink itself; macOS/BSD mv lacks -T, so the pointer
# is unlinked and recreated (per-user install; the brief window is documented).
if [[ "$(uname -s)" == "Darwin" ]]; then
    rm -f -- "$INSTALL_ROOT/current"
    mv -- "$CURRENT_TMP" "$INSTALL_ROOT/current"
else
    mv -fT -- "$CURRENT_TMP" "$INSTALL_ROOT/current"
fi
ln -s "$INSTALL_ROOT/current/bin/quantumforge" "$LINK_TMP"
mv -f -- "$LINK_TMP" "$BIN_DIR/quantumforge"

# Fail-closed self-check: never report success for an activation that did not
# actually happen (see the symlink-to-directory note above).
if [[ "$(readlink "$INSTALL_ROOT/current")" != "versions/$VERSION" ]]; then
    echo "Activation failed: current pointer did not switch to $VERSION." >&2
    exit 5
fi
if [[ "$(readlink "$BIN_DIR/quantumforge")" != "$INSTALL_ROOT/current/bin/quantumforge" ]]; then
    echo "Activation failed: $BIN_DIR/quantumforge does not point at the installation." >&2
    exit 5
fi

# Add a per-user desktop entry on Linux. It contains an installation marker so
# uninstall removes only the file created here.
if [[ "$(uname -s)" == "Linux" ]]; then
    DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/quantumforge.desktop.tmp.$$" <<EOF
[Desktop Entry]
# Managed-By=QuantumForge-Installer
Type=Application
Name=QuantumForge
Comment=Quantum ESPRESSO workflow editor and results viewer
Exec="$BIN_DIR/quantumforge"
Icon=$INSTALL_ROOT/current/resources/quantumforge.png
Terminal=false
Categories=Science;Education;Physics;
StartupNotify=true
EOF
    mv -f "$DESKTOP_DIR/quantumforge.desktop.tmp.$$" "$DESKTOP_DIR/quantumforge.desktop"
fi

trap - EXIT HUP INT TERM
printf 'QuantumForge %s installed safely.\n' "$VERSION"
printf 'Command: %s/quantumforge\n' "$BIN_DIR"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) printf '\nAdd this line to your shell profile, then open a new terminal:\n  export PATH="%s:$PATH"\n' "$BIN_DIR" ;;
esac
printf '\nRun: quantumforge --doctor\nThen review: quantumforge --capabilities\n'
