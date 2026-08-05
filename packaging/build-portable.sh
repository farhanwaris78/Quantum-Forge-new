#!/usr/bin/env bash
# Build a platform-specific portable archive using Maven-resolved JavaFX natives.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
VERSION="$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' pom.xml | head -1)"
[[ -n "$VERSION" ]] || { echo "Could not read project version." >&2; exit 2; }
PLATFORM="${1:-}"
MACHINE="${2:-}"
case "$PLATFORM" in linux|macos) ;;
    *) echo "Usage: packaging/build-portable.sh <linux|macos> <x64|arm64>" >&2; exit 2 ;;
esac
case "$MACHINE" in x64|arm64) ;;
    *) echo "Unsupported architecture: $MACHINE" >&2; exit 2 ;;
esac

mvn -B -ntp -DskipTests clean verify
NAME="QuantumForge-$VERSION-$PLATFORM-$MACHINE"
BUNDLE="$ROOT/target/portable/$NAME"
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/app" "$BUNDLE/lib/javafx" "$BUNDLE/bin" \
    "$BUNDLE/management" "$BUNDLE/resources" "$BUNDLE/docs"
cp target/quantumforge.jar "$BUNDLE/app/"

case "$PLATFORM" in linux) FX_CLASSIFIER=linux ;; macos) FX_CLASSIFIER=mac ;;
esac
shopt -s nullglob
FX_PLATFORM_JARS=(target/dependency/javafx-*-${FX_CLASSIFIER}.jar)
if ((${#FX_PLATFORM_JARS[@]} == 0)); then
    echo "No JavaFX $FX_CLASSIFIER native libraries were resolved; refusing broken archive." >&2
    exit 3
fi
cp "${FX_PLATFORM_JARS[@]}" "$BUNDLE/lib/javafx/"
for jar in target/dependency/*.jar; do
    [[ "$(basename "$jar")" == javafx-* ]] && continue
    cp "$jar" "$BUNDLE/lib/"
done

cp packaging/unix/quantumforge "$BUNDLE/bin/quantumforge"
cp packaging/windows/quantumforge.cmd "$BUNDLE/bin/quantumforge.cmd"
cp packaging/unix/install.sh "$BUNDLE/management/install.sh"
cp packaging/unix/update.sh "$BUNDLE/management/update.sh"
cp packaging/unix/uninstall.sh "$BUNDLE/management/uninstall.sh"
cp packaging/windows/Install-QuantumForge.ps1 "$BUNDLE/management/Install-QuantumForge.ps1"
cp packaging/windows/Update-QuantumForge.ps1 "$BUNDLE/management/Update-QuantumForge.ps1"
cp packaging/windows/Uninstall-QuantumForge.ps1 "$BUNDLE/management/Uninstall-QuantumForge.ps1"
cp packaging/unix/install.sh "$BUNDLE/install.sh"
cp packaging/unix/update.sh "$BUNDLE/update.sh"
cp packaging/unix/uninstall.sh "$BUNDLE/uninstall.sh"
cp LICENSE README.md "$BUNDLE/"
cp docs/INSTALLATION.md docs/RELEASE_AND_SECURITY.md docs/SCIENTIFIC_SOFTWARE_GUIDE.md \
   docs/CODE_AUDIT.md docs/ROADMAP.md \
   docs/TUTORIAL_INSTALL.md "$BUNDLE/docs/" 2>/dev/null || \
cp docs/INSTALLATION.md docs/RELEASE_AND_SECURITY.md docs/SCIENTIFIC_SOFTWARE_GUIDE.md \
   docs/CODE_AUDIT.md docs/ROADMAP.md "$BUNDLE/docs/"
cp src/quantumforge/app/resource/image/icon_256.png "$BUNDLE/resources/quantumforge.png"
printf '%s\n' "$VERSION" > "$BUNDLE/VERSION"
printf 'command=quantumforge\n' > "$BUNDLE/LAUNCH_COMMAND.txt"
cp target/quantumforge-sbom.json "$BUNDLE/quantumforge-sbom.cdx.json"
chmod 755 "$BUNDLE/bin/quantumforge" "$BUNDLE/management/"*.sh \
    "$BUNDLE/install.sh" "$BUNDLE/update.sh" "$BUNDLE/uninstall.sh"
find "$BUNDLE" -type f ! -path '*/bin/quantumforge' ! -path '*/management/*.sh' ! -name install.sh -exec chmod 644 {} +

mkdir -p target/release
ARCHIVE="$ROOT/target/release/$NAME.tar.gz"
# Sorted names and fixed mtimes make archives reproducible for a given dependency set.
if tar --version 2>/dev/null | grep -q GNU; then
    tar --sort=name --mtime="@${SOURCE_DATE_EPOCH:-0}" --owner=0 --group=0 --numeric-owner \
        -czf "$ARCHIVE" -C "$(dirname "$BUNDLE")" "$(basename "$BUNDLE")"
else
    COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" -C "$(dirname "$BUNDLE")" "$(basename "$BUNDLE")"
fi
printf '%s\n' "$ARCHIVE"
