#!/usr/bin/env bash
# Build a self-contained jpackage app image or native installer on Linux/macOS.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
TYPE="${1:-app-image}"
case "$TYPE" in app-image|deb|rpm|dmg|pkg) ;;
    *) echo "Usage: packaging/build-native.sh [app-image|deb|rpm|dmg|pkg]" >&2; exit 2 ;;
esac
command -v jpackage >/dev/null || { echo "jpackage from JDK 17+ is required." >&2; exit 2; }
VERSION="$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' pom.xml | head -1)"

mvn -B -ntp -DskipTests clean verify
INPUT="$ROOT/target/jpackage-input"
FX_PATH="$ROOT/target/jpackage-javafx"
DEST="$ROOT/target/native"
rm -rf "$INPUT" "$FX_PATH"
mkdir -p "$INPUT" "$FX_PATH" "$DEST"
cp target/quantumforge.jar "$INPUT/"
for jar in target/dependency/*.jar; do
    if [[ "$(basename "$jar")" == javafx-* ]]; then
        # Generic OpenJFX metadata JARs and platform JARs can define the same
        # module. Retain only the native platform variants.
        case "$(uname -s)" in
            Linux) [[ "$(basename "$jar")" == *-linux.jar ]] && cp "$jar" "$FX_PATH/" ;;
            Darwin) [[ "$(basename "$jar")" == *-mac.jar ]] && cp "$jar" "$FX_PATH/" ;;
        esac
    else
        cp "$jar" "$INPUT/"
    fi
done
[[ -n "$(find "$FX_PATH" -name 'javafx-graphics-*.jar' -print -quit)" ]] || {
    echo "Platform JavaFX modules are missing." >&2; exit 3;
}

OS="$(uname -s)"
if [[ "$OS" == Darwin ]]; then NAME=QuantumForge; else NAME=quantumforge; fi
ARGS=(
    --type "$TYPE"
    --dest "$DEST"
    --name "$NAME"
    --app-version "$VERSION"
    --vendor "QuantumForge Development Team"
    --description "Quantum ESPRESSO workflow editor and results viewer"
    --copyright "Copyright (C) 2025-2026 QuantumForge Development Team"
    --license-file "$ROOT/LICENSE"
    --input "$INPUT"
    --main-jar quantumforge.jar
    --main-class quantumforge.launcher.QuantumForgeLauncher
    --module-path "$FX_PATH"
    --add-modules javafx.controls,javafx.fxml,javafx.web,javafx.swing,java.logging,jdk.crypto.ec
    --java-options -Dfile.encoding=UTF-8
)
if [[ "$OS" == Linux ]]; then
    ARGS+=(--icon "$ROOT/src/quantumforge/app/resource/image/icon_256.png")
    if [[ "$TYPE" == deb || "$TYPE" == rpm ]]; then
        ARGS+=(--linux-package-name quantumforge --linux-shortcut --linux-menu-group Science)
    fi
    if [[ "$TYPE" == deb ]]; then ARGS+=(--linux-deb-maintainer license@quantumforge.ai); fi
elif [[ "$OS" == Darwin ]]; then
    ARGS+=(--mac-package-name QuantumForge)
fi
jpackage "${ARGS[@]}"
find "$DEST" -maxdepth 1 -mindepth 1 -print
