#!/usr/bin/env bash
# Conservative uninstaller for the unprivileged portable installation.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_HOME="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
INSTALL_ROOT="$(CDPATH= cd -- "$APP_HOME/../.." && pwd -P)"
YES=0
PURGE=0

while (($#)); do
    case "$1" in
        --yes) YES=1; shift ;;
        --purge) PURGE=1; shift ;;
        --help|-h)
            cat <<'EOF'
Usage: quantumforge --uninstall [--yes] [--purge]

By default, removes only installed application versions, launcher, and desktop
entry. ~/.quantumforge (projects, settings, pseudopotentials, logs) is preserved.
--purge also deletes ~/.quantumforge and therefore requires explicit confirmation.
EOF
            exit 0 ;;
        *) echo "Unknown uninstall option: $1" >&2; exit 2 ;;
    esac
done

# Refuse dangerous or unrelated paths even if this script was copied elsewhere.
[[ -f "$APP_HOME/INSTALL_RECEIPT" && -d "$INSTALL_ROOT/versions" ]] || {
    echo "This does not look like an installer-managed QuantumForge installation." >&2
    exit 3
}
case "$INSTALL_ROOT" in
    /|"$HOME"|"$HOME/.local"|"") echo "Unsafe installation root; refusing removal." >&2; exit 3 ;;
esac

if ((PURGE)); then
    echo "WARNING: --purge permanently deletes $HOME/.quantumforge, including projects and settings."
fi
printf 'Uninstall QuantumForge from %s? [y/N] ' "$INSTALL_ROOT"
if ((YES)) && ((!PURGE)); then echo y; answer=y; else read -r answer || answer=''; fi
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Uninstall cancelled."; exit 0; }

BIN_DIR="$(sed -n 's/^bin_dir=//p' "$APP_HOME/INSTALL_RECEIPT" | head -1)"
if [[ -n "$BIN_DIR" && -L "$BIN_DIR/quantumforge" ]]; then
    LINK_TARGET="$(readlink "$BIN_DIR/quantumforge" || true)"
    case "$LINK_TARGET" in "$INSTALL_ROOT"/*) rm -f -- "$BIN_DIR/quantumforge" ;; esac
fi

if [[ "$(uname -s)" == "Linux" ]]; then
    DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/quantumforge.desktop"
    if [[ -f "$DESKTOP" ]] && grep -q '^# Managed-By=QuantumForge-Installer$' "$DESKTOP"; then
        rm -f -- "$DESKTOP"
    fi
fi

rm -rf -- "$INSTALL_ROOT"
if ((PURGE)); then
    rm -rf -- "$HOME/.quantumforge"
    echo "QuantumForge and its user data were removed."
else
    echo "QuantumForge was removed. Research data remains in $HOME/.quantumforge"
fi
