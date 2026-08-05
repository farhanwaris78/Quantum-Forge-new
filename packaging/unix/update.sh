#!/usr/bin/env bash
# Verified update client for portable user installations.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "$SCRIPT_DIR/VERSION" ]]; then
    # Top-level convenience copy inside an unpacked download. There is no
    # installed layout to update; refuse instead of deriving a bogus root
    # from the download directory.
    echo "This update.sh sits inside an unpacked download, not an installation." >&2
    echo "Install first (./install.sh), then run: quantumforge --update" >&2
    exit 2
fi
APP_HOME="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)"
INSTALL_ROOT="$(CDPATH= cd -- "$APP_HOME/../.." && pwd -P)"
REPOSITORY="${QUANTUMFORGE_UPDATE_REPOSITORY:-farhanwaris78/Quantum-Forge}"
API_BASE="${QUANTUMFORGE_UPDATE_API_BASE:-https://api.github.com}"

# Fail-closed layout proof, mirroring uninstall.sh: update only a real
# installer-managed tree, never an arbitrary directory this script was copied into.
[[ -f "$APP_HOME/INSTALL_RECEIPT" && -d "$INSTALL_ROOT/versions" ]] || {
    echo "This does not look like an installer-managed QuantumForge installation." >&2
    echo "Nothing was downloaded or changed." >&2
    exit 3
}

# Transport policy: HTTPS always. Plain HTTP is accepted only on loopback so a
# site mirror or the packaging smoke test can run locally; anything else is refused.
case "$API_BASE" in
    https://*) CURL_PROTOCOLS="=https" ;;
    http://127.0.0.1*|http://localhost*|http://\[::1\]*)
        CURL_PROTOCOLS="http,https"
        echo "NOTE: plain-HTTP update mirror on loopback ($API_BASE); production updates use HTTPS." >&2
        ;;
    *)
        echo "Refusing QUANTUMFORGE_UPDATE_API_BASE=$API_BASE (only https:// or loopback http allowed)." >&2
        exit 2
        ;;
esac
API="$API_BASE/repos/$REPOSITORY/releases/latest"
YES=0

while (($#)); do
    case "$1" in
        --yes) YES=1; shift ;;
        --help|-h)
            echo "Usage: quantumforge --update [--yes]"
            echo "Downloads the latest release, verifies SHA-256, and atomically activates it."
            echo "Environment overrides:"
            echo "  QUANTUMFORGE_UPDATE_REPOSITORY  owner/name (default farhanwaris78/Quantum-Forge)"
            echo "  QUANTUMFORGE_UPDATE_API_BASE    GitHub-compatible API base (https only;"
            echo "                                  loopback http allowed for local mirrors/tests)"
            exit 0 ;;
        *) echo "Unknown update option: $1" >&2; exit 2 ;;
    esac
done

for command in curl python3 tar; do
    command -v "$command" >/dev/null || {
        echo "Update requires '$command'. Install it or update using a downloaded release bundle." >&2
        exit 2
    }
done

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
    Linux) PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *) echo "This updater supports Linux and macOS; use Install-QuantumForge.ps1 on Windows." >&2; exit 2 ;;
esac
case "$ARCH" in
    x86_64|amd64) MACHINE=x64 ;;
    arm64|aarch64) MACHINE=arm64 ;;
    *) echo "Unsupported architecture: $ARCH" >&2; exit 2 ;;
esac

TMP="$(mktemp -d "${TMPDIR:-/tmp}/quantumforge-update.XXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT HUP INT TERM
curl --proto "$CURL_PROTOCOLS" --tlsv1.2 --fail --silent --show-error --location \
    --retry 3 --output "$TMP/release.json" "$API"

python3 - "$TMP/release.json" "$PLATFORM" "$MACHINE" "$TMP/release-data" <<'PY'
import json, re, sys
with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)
if release.get("draft") or release.get("prerelease"):
    raise SystemExit("Latest GitHub release is not a stable published release")
platform, machine = map(re.escape, sys.argv[2:4])
pattern = re.compile(rf"^QuantumForge-([0-9][0-9A-Za-z.\-]*)-{platform}-{machine}\.tar\.gz$")
archive = checksum = None
for asset in release.get("assets", []):
    name = asset.get("name", "")
    match = pattern.match(name)
    if match:
        archive = (name, asset["browser_download_url"], match.group(1))
    elif name == "SHA256SUMS":
        checksum = asset["browser_download_url"]
if not archive or not checksum:
    raise SystemExit(f"Release has no verified archive for {sys.argv[2]}-{sys.argv[3]}")
with open(sys.argv[4], "w", encoding="utf-8") as stream:
    stream.write("\n".join((*archive, checksum)) + "\n")
PY

[[ "$(wc -l < "$TMP/release-data" | tr -d ' ')" == 4 ]] || {
    echo "Could not identify a verified release asset." >&2
    exit 3
}
ASSET_NAME="$(sed -n '1p' "$TMP/release-data")"
ASSET_URL="$(sed -n '2p' "$TMP/release-data")"
LATEST_VERSION="$(sed -n '3p' "$TMP/release-data")"
CHECKSUM_URL="$(sed -n '4p' "$TMP/release-data")"
CURRENT_VERSION="$(tr -d '[:space:]' < "$APP_HOME/VERSION")"
if [[ "$CURRENT_VERSION" == "$LATEST_VERSION" ]]; then
    echo "QuantumForge $CURRENT_VERSION is already current."
    exit 0
fi

printf 'Update QuantumForge %s -> %s? [y/N] ' "$CURRENT_VERSION" "$LATEST_VERSION"
if ((YES)); then echo y; answer=y; else read -r answer || answer=''; fi
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Update cancelled."; exit 0; }

curl --proto "$CURL_PROTOCOLS" --tlsv1.2 --fail --silent --show-error --location \
    --retry 3 --output "$TMP/$ASSET_NAME" "$ASSET_URL"
curl --proto "$CURL_PROTOCOLS" --tlsv1.2 --fail --silent --show-error --location \
    --retry 3 --output "$TMP/SHA256SUMS" "$CHECKSUM_URL"

EXPECTED="$(awk -v file="$ASSET_NAME" '$2 == file || $2 == "*" file {print $1}' "$TMP/SHA256SUMS")"
[[ "$EXPECTED" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "Release checksum is missing or malformed." >&2; exit 4; }
if command -v sha256sum >/dev/null; then
    ACTUAL="$(sha256sum "$TMP/$ASSET_NAME" | awk '{print $1}')"
else
    ACTUAL="$(shasum -a 256 "$TMP/$ASSET_NAME" | awk '{print $1}')"
fi
ACTUAL_LOWER="$(printf '%s' "$ACTUAL" | tr '[:upper:]' '[:lower:]')"
EXPECTED_LOWER="$(printf '%s' "$EXPECTED" | tr '[:upper:]' '[:lower:]')"
[[ "$ACTUAL_LOWER" == "$EXPECTED_LOWER" ]] || { echo "SHA-256 verification FAILED; nothing was installed." >&2; exit 4; }

# Reject absolute paths and parent traversal before extraction.
if tar -tzf "$TMP/$ASSET_NAME" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    echo "Unsafe path in release archive; refusing to extract." >&2
    exit 4
fi
mkdir "$TMP/extracted"
tar -xzf "$TMP/$ASSET_NAME" -C "$TMP/extracted"
INSTALLER="$(find "$TMP/extracted" -mindepth 2 -maxdepth 3 -type f -path '*/management/install.sh' -print -quit)"
[[ -n "$INSTALLER" ]] || { echo "Release archive has no installer." >&2; exit 4; }
chmod +x "$INSTALLER"
"$INSTALLER" --prefix "$INSTALL_ROOT" --yes

echo "Update complete. Your existing ~/.quantumforge research data was preserved."
