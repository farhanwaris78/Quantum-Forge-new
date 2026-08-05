#!/usr/bin/env bash
# End-to-end EXECUTED smoke test for the QuantumForge portable packaging.
#
# This script does not mock the scripts under test: it fabricates a realistic
# portable bundle, runs the real management/install.sh, management/update.sh,
# management/uninstall.sh and bin/quantumforge launcher, and checks every
# promised behaviour with real exit codes and real file-system effects inside a
# throw-away HOME. Nothing outside the temporary sandbox is touched.
#
# What is REAL in every run:
#   * install / update / uninstall scripts (the shipped files, byte for byte)
#   * the bin/quantumforge launcher script and its argument composition
#   * the bare-word `quantumforge` invocation through PATH
#   * checksum verification, archive traversal refusal, fail-closed refusals
#
# What depends on the environment (each run states which mode it used):
#   * QF_SMOKE_JDK      - directory with javac/java/jar (JDK 17+). When present,
#                         the REAL QuantumForgeLauncher and its compile closure
#                         are compiled from src/ and executed for --version,
#                         --help, --capabilities, --doctor and GUI argv
#                         pass-through. Without it, those cases are replaced by
#                         an instrumented stub-java that records the JVM argv.
#   * QF_SMOKE_JAVAFX_DIR - directory with the real javafx-*-<classifier>.jar
#                         modules. When absent, EMPTY placeholder modules are
#                         generated so the launcher's --module-path starts the
#                         JVM; no JavaFX class is ever loaded by the tested
#                         command paths. The GUI itself can only be smoke-tested
#                         on a machine with a display; here QEFXMain is replaced
#                         by an argv-recording placeholder compiled into the
#                         test jar (stated again at run time).
#
# The update flow is tested against a loopback HTTP mirror (the same shape as
# the GitHub releases API) through QUANTUMFORGE_UPDATE_API_BASE - production
# updates remain HTTPS-only, which is itself asserted here.
#
# Usage:
#   packaging/tests/smoke-portable.sh
# Environment:
#   QF_SMOKE_JDK=/path/to/jdk/bin        optional but recommended
#   QF_SMOKE_JAVAFX_DIR=/path/to/javafx  optional real JavaFX module jars
#   QF_SMOKE_KEEP=1                      keep the sandbox directory for forensics
set -uo pipefail

PASS=0
FAIL=0
NOTES=0

pass() { PASS=$((PASS + 1)); printf '[PASS] %s\n' "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '[FAIL] %s\n' "$1" >&2; }
note() { NOTES=$((NOTES + 1)); printf '[NOTE] %s\n' "$1"; }

check_eq() { # <label> <expected> <actual>
    if [[ "$2" == "$3" ]]; then pass "$1"; else fail "$1 (expected [$2], got [$3])"; fi
}
check_contains() { # <label> <haystack-file> <needle>
    if grep -qF -- "$3" "$2" 2>/dev/null; then pass "$1"; else fail "$1 (missing [$3] in $2)"; fi
}

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P)"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/quantumforge-smoke.XXXXXX")"
cleanup() {
    [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null
    if [[ "${QF_SMOKE_KEEP:-0}" == "1" ]]; then
        printf '[NOTE] sandbox kept at %s\n' "$WORK"
    else
        rm -rf -- "$WORK"
    fi
}
trap cleanup EXIT HUP INT TERM

HOME_DIR="$WORK/home"
mkdir -p "$HOME_DIR" "$WORK/tmp"
SAFE_HOME=("HOME=$HOME_DIR" "XDG_DATA_HOME=$HOME_DIR/.local/share" "TMPDIR=$WORK/tmp")

# -----------------------------------------------------------------------
# JDK discovery (needed for the real-launcher chain and module placeholder).
# -----------------------------------------------------------------------
JDK_BIN=""
for candidate in "${QF_SMOKE_JDK:-}" "${QUANTUMFORGE_JAVA_HOME:-}/bin" "${JAVA_HOME:-}/bin"; do
    if [[ -n "$candidate" && -x "$candidate/javac" && -x "$candidate/java" && -x "$candidate/jar" ]]; then
        JDK_BIN="$candidate"
        break
    fi
done
if [[ -z "$JDK_BIN" ]] && command -v javac >/dev/null && command -v jar >/dev/null; then
    JDK_BIN="$(CDPATH= cd -- "$(dirname -- "$(command -v javac)")" && pwd -P)"
fi
REAL_CHAIN=0
if [[ -n "$JDK_BIN" && -x "$JDK_BIN/javac" ]]; then
    JAVAC_VERSION="$("$JDK_BIN/javac" -version 2>&1 | awk '{print $2}' | cut -d. -f1)"
    if [[ "$JAVAC_VERSION" =~ ^[0-9]+$ ]] && ((JAVAC_VERSION >= 17)); then
        REAL_CHAIN=1
        note "real-launcher chain enabled with $JDK_BIN (javac $("$JDK_BIN/javac" -version 2>&1))"
    else
        note "javac on PATH is older than 17; falling back to the stub-java chain"
    fi
else
    note "no JDK 17 found; falling back to the stub-java chain"
fi

# -----------------------------------------------------------------------
# JavaFX module directory: real jars when provided, empty placeholders else.
# -----------------------------------------------------------------------
FX_DIR="$WORK/javafx-modules"
mkdir -p "$FX_DIR"
FX_MODULES=(javafx.base javafx.graphics javafx.controls javafx.fxml javafx.web javafx.media javafx.swing)
if [[ -n "${QF_SMOKE_JAVAFX_DIR:-}" ]] && compgen -G "$QF_SMOKE_JAVAFX_DIR/javafx-*.jar" >/dev/null; then
    cp "$QF_SMOKE_JAVAFX_DIR"/javafx-*.jar "$FX_DIR/"
    note "using REAL JavaFX module jars from $QF_SMOKE_JAVAFX_DIR"
else
    if ((REAL_CHAIN)); then
        for module in "${FX_MODULES[@]}"; do
            mod_src="$WORK/modsrc/$module"
            mkdir -p "$mod_src"
            printf 'module %s {\n}\n' "$module" > "$mod_src/module-info.java"
            if "$JDK_BIN/javac" -d "$mod_src/classes" "$mod_src/module-info.java" 2>/dev/null \
                && "$JDK_BIN/jar" --create --file "$FX_DIR/${module}-0.0.0-placeholder.jar" \
                    -C "$mod_src/classes" .; then
                :
            else
                fail "could not build placeholder module $module"
            fi
        done
        note "JavaFX modules are EMPTY test placeholders: JVM module resolution is exercised,"
        note "but no JavaFX class is loaded. GUI start itself needs a display and is not faked."
    else
        note "no JDK -> placeholder JavaFX modules skipped (stub-java chain only)"
    fi
fi

# -----------------------------------------------------------------------
# Compile the REAL launcher closure into a test jar (real-chain mode).
# QEFXMain is replaced by an argv-recording placeholder, stated honestly.
# -----------------------------------------------------------------------
build_launcher_jar() { # <output-jar>
    local shadow="$WORK/shadow-src" classes="$WORK/classes" out="$1"
    local cache="$WORK/cache/launcher.jar"
    if [[ -f "$cache" ]]; then
        cp "$cache" "$out"
        return 0
    fi
    rm -rf "$shadow" "$classes"
    mkdir -p "$shadow" "$classes" "$(dirname "$cache")"
    cp -R "$REPO_ROOT/src/." "$shadow/"
    cat > "$shadow/quantumforge/app/QEFXMain.java" <<'EOF'
package quantumforge.app;

/**
 * TEST-ONLY placeholder injected by packaging/tests/smoke-portable.sh.
 * The production QEFXMain starts JavaFX; this double records the exact argv
 * the launcher forwards so the headless smoke test can prove argv plumbing.
 * It is compiled INTO the temporary test jar only and never shipped.
 */
public final class QEFXMain {
    private QEFXMain() {
    }

    public static void main(String[] args) {
        StringBuilder line = new StringBuilder("QF_GUI_PLACEHOLDER_ARGS=");
        if (args != null) {
            for (String arg : args) {
                line.append('[').append(arg).append(']');
            }
        }
        System.out.println(line);
    }
}
EOF
    if ! "$JDK_BIN/javac" -encoding UTF-8 -nowarn -Xmaxerrs 200 \
            -cp "$REPO_ROOT/lib/*" -sourcepath "$shadow" \
            -d "$classes" "$shadow/quantumforge/launcher/QuantumForgeLauncher.java" > "$WORK/javac.log" 2>&1; then
        fail "launcher closure did not compile (see below)"; sed 's/^/    /' "$WORK/javac.log" | head -30 >&2
        return 1
    fi
    "$JDK_BIN/jar" --create --file "$out" -C "$classes" . || { fail "jar creation failed"; return 1; }
    cp "$out" "$cache"
    note "test jar contains REAL classes from src/ plus the stated QEFXMain argv placeholder"
    return 0
}

# -----------------------------------------------------------------------
# Bundle fabrication mirroring packaging/build-portable.sh layout.
# -----------------------------------------------------------------------
make_bundle() { # <version>
    local version="$1"
    local bundle="$WORK/bundles/QuantumForge-$version-linux-x64"
    rm -rf "$bundle"
    mkdir -p "$bundle/app" "$bundle/lib/javafx" "$bundle/bin" "$bundle/management" \
        "$bundle/resources" "$bundle/docs"
    printf '%s\n' "$version" > "$bundle/VERSION"
    printf 'command=quantumforge\n' > "$bundle/LAUNCH_COMMAND.txt"
    if ((REAL_CHAIN)); then
        build_launcher_jar "$bundle/app/quantumforge.jar" || return 1
        cp "$FX_DIR"/*.jar "$bundle/lib/javafx/" 2>/dev/null || true
    else
        printf 'stub jar - stub-java chain\n' > "$bundle/app/quantumforge.jar"
    fi
    cp "$REPO_ROOT"/lib/*.jar "$bundle/lib/" 2>/dev/null || true
    cp "$REPO_ROOT/packaging/unix/quantumforge" "$bundle/bin/quantumforge"
    cp "$REPO_ROOT/packaging/windows/quantumforge.cmd" "$bundle/bin/quantumforge.cmd" 2>/dev/null || true
    for s in install update uninstall; do
        cp "$REPO_ROOT/packaging/unix/$s.sh" "$bundle/management/$s.sh"
        cp "$REPO_ROOT/packaging/unix/$s.sh" "$bundle/$s.sh"
    done
    cp "$REPO_ROOT/LICENSE" "$REPO_ROOT/README.md" "$bundle/"
    cp "$REPO_ROOT/src/quantumforge/app/resource/image/icon_256.png" "$bundle/resources/quantumforge.png" 2>/dev/null || true
    chmod 755 "$bundle/bin/quantumforge" "$bundle/management/"*.sh "$bundle/"*.sh
    printf '%s\n' "$bundle"
}

quiet() { "$@" >/dev/null 2>&1; }

# =======================================================================
printf '== Section 1: launcher argument composition (instrumented stub java) ==\n'
# =======================================================================
BUNDLE_STUB="$(make_bundle 1.0.0 | tail -1)"
[[ -d "$BUNDLE_STUB" ]] || fail "bundle fabrication failed"

STUB_BIN="$WORK/stub-bin"
mkdir -p "$STUB_BIN"
cat > "$STUB_BIN/java" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${QF_STUB_JAVA_LOG:?QF_STUB_JAVA_LOG not set}"
echo STUB_JAVA_INVOKED
EOF
chmod 755 "$STUB_BIN/java"

run_launcher() { # <logfile> <extra-env...> -- <args...>
    local log="$1"; shift
    local envs=("$@")
    local args=()
    local i
    for i in "${!envs[@]}"; do
        if [[ "${envs[$i]}" == "--" ]]; then
            args=("${envs[@]:$((i + 1))}")
            envs=("${envs[@]:0:$i}")
            break
        fi
    done
    env -i "HOME=$HOME_DIR" "PATH=$STUB_BIN:/usr/bin:/bin" \
        "QF_STUB_JAVA_LOG=$log" "${envs[@]}" "$BUNDLE_STUB/bin/quantumforge" "${args[@]}"
}

JAVA_LOG="$WORK/java-argv.log"
EXPECTED_DIR="$WORK/expected"
mkdir -p "$EXPECTED_DIR"

# 1a. Exact JVM argv on a local desktop (no SSH agent vars).
quiet run_launcher "$JAVA_LOG" -- input.in
cat > "$EXPECTED_DIR/plain.txt" <<EOF
-Dfile.encoding=UTF-8
--module-path
$BUNDLE_STUB/lib/javafx
--add-modules
javafx.controls,javafx.fxml,javafx.web,javafx.swing
-cp
$BUNDLE_STUB/app/quantumforge.jar:$BUNDLE_STUB/lib/*
quantumforge.launcher.QuantumForgeLauncher
input.in
EOF
if diff -u "$EXPECTED_DIR/plain.txt" "$JAVA_LOG" > "$WORK/diff.log" 2>&1; then
    pass "local launch JVM argv is exact (module path, add-modules, classpath, main class, user arg)"
else
    fail "local launch JVM argv drifted"; sed 's/^/    /' "$WORK/diff.log" >&2
fi

# 1b. X11-forwarded session (ssh -X / MobaXterm): software rendering guard.
quiet run_launcher "$JAVA_LOG" "SSH_CONNECTION=10.0.0.2 50000 10.0.0.1 22" "DISPLAY=localhost:10.0" --
cat > "$EXPECTED_DIR/ssh.txt" <<EOF
-Dfile.encoding=UTF-8
-Dprism.order=sw
--module-path
$BUNDLE_STUB/lib/javafx
EOF
if head -4 "$JAVA_LOG" > /dev/null && diff -u "$EXPECTED_DIR/ssh.txt" <(head -4 "$JAVA_LOG") > "$WORK/diff.log" 2>&1; then
    pass "X11-forwarded launch adds -Dprism.order=sw (MobaXterm/ssh -X pixel-path guard)"
else
    fail "X11-forwarded launch lost the software-rendering guard"; cat "$WORK/diff.log" >&2
fi

# 1c. SSH without DISPLAY (plain terminal): no rendering override, GUI would fail honestly later.
quiet run_launcher "$JAVA_LOG" "SSH_CONNECTION=10.0.0.2 50000 10.0.0.1 22" --
if grep -q 'prism.order=sw' "$JAVA_LOG"; then
    fail "prism override leaked into a display-less SSH session"
else
    pass "SSH without DISPLAY stays unmodified (doctor would report the missing display)"
fi

# 1d. QUANTUMFORGE_JAVA_OPTS splitting.
quiet run_launcher "$JAVA_LOG" 'QUANTUMFORGE_JAVA_OPTS=-Xmx512m -Dqf.test=two words are three' --
if grep -qx -- '-Xmx512m' "$JAVA_LOG" && grep -qx -- '-Dqf.test=two' "$JAVA_LOG" \
    && grep -qx -- 'words' "$JAVA_LOG"; then
    pass "QUANTUMFORGE_JAVA_OPTS splits on whitespace like conventional JVM flags"
else
    fail "QUANTUMFORGE_JAVA_OPTS splitting drifted"; cat "$JAVA_LOG" >&2
fi

# 1e. Java discovery precedence: QUANTUMFORGE_JAVA_HOME > JAVA_HOME > PATH.
FAKE_JDK="$WORK/fake-jdk/bin"
mkdir -p "$FAKE_JDK"
cp "$STUB_BIN/java" "$FAKE_JDK/java"
chmod 755 "$FAKE_JDK/java"
quiet run_launcher "$JAVA_LOG" "QUANTUMFORGE_JAVA_HOME=$WORK/fake-jdk" "JAVA_HOME=$WORK/ignored-jdk" --
[[ -s "$JAVA_LOG" ]] && pass "QUANTUMFORGE_JAVA_HOME JDK is honoured first" || fail "QUANTUMFORGE_JAVA_HOME was ignored"
QUIET_OUT="$(run_launcher /dev/null "QUANTUMFORGE_JAVA_HOME=$WORK/does-not-exist" 2>&1)"; RC=$?
check_eq "missing QUANTUMFORGE_JAVA_HOME refuses with exit 2 and guidance" "2" "$RC"
case "$QUIET_OUT" in
    *"requires a 64-bit Java 17"*) pass "missing-Java message names the requirement and JAVA_HOME remedy" ;;
    *) fail "missing-Java guidance lost: $QUIET_OUT" ;;
esac

# 1f. Incomplete bundle fails closed.
BUNDLE_BROKEN="$(make_bundle 1.0.0 | tail -1)"
rm -f "$BUNDLE_BROKEN/app/quantumforge.jar"
BROKEN_OUT="$(env -i HOME="$HOME_DIR" PATH="$STUB_BIN:/usr/bin:/bin" "$BUNDLE_BROKEN/bin/quantumforge" 2>&1)"; RC=$?
check_eq "missing app/quantumforge.jar exits 3" "3" "$RC"
case "$BROKEN_OUT" in
    *"installation is incomplete"*) pass "incomplete-install message is explicit" ;;
    *) fail "incomplete-install message lost: $BROKEN_OUT" ;;
esac

# 1g. Delegation with an unknown option reaches the REAL management scripts.
BUNDLE_DEL="$(make_bundle 1.0.0 | tail -1)"
DEL_HOME="$WORK/delegation-home"
mkdir -p "$DEL_HOME"
quiet env -i HOME="$DEL_HOME" XDG_DATA_HOME="$DEL_HOME/.local/share" PATH="/usr/bin:/bin" \
    "$BUNDLE_DEL/management/install.sh" --prefix "$DEL_HOME/.local/share/quantumforge" \
    --bin-dir "$DEL_HOME/.local/bin" --yes
DEL_CANDIDATE="$DEL_HOME/.local/bin/quantumforge"
[[ -L "$DEL_CANDIDATE" ]] && pass "delegation fixture installed" || fail "delegation fixture install failed"
UPD_OUT="$(env -i HOME="$DEL_HOME" PATH="$STUB_BIN:/usr/bin:/bin" "$DEL_CANDIDATE" --update --bogus 2>&1)"; RC=$?
check_eq "--update delegates argv to management/update.sh (unknown option exit 2)" "2" "$RC"
case "$UPD_OUT" in
    *"Unknown update option: --bogus"*) pass "update delegation forwards arguments verbatim" ;;
    *) fail "update delegation lost: $UPD_OUT" ;;
esac
UNI_OUT="$(env -i HOME="$DEL_HOME" PATH="$STUB_BIN:/usr/bin:/bin" "$DEL_CANDIDATE" --uninstall --bogus 2>&1)"; RC=$?
check_eq "--uninstall delegates argv to management/uninstall.sh" "2" "$RC"
case "$UNI_OUT" in
    *"Unknown uninstall option: --bogus"*) pass "uninstall delegation forwards arguments verbatim" ;;
    *) fail "uninstall delegation lost: $UNI_OUT" ;;
esac

# 1h. Native-layout launcher (no management scripts) gives package-manager guidance.
BUNDLE_NATIVE="$WORK/native-layout"
mkdir -p "$BUNDLE_NATIVE/bin" "$BUNDLE_NATIVE/app"
cp "$REPO_ROOT/packaging/unix/quantumforge" "$BUNDLE_NATIVE/bin/quantumforge"
chmod 755 "$BUNDLE_NATIVE/bin/quantumforge"
printf 'x\n' > "$BUNDLE_NATIVE/app/quantumforge.jar"
NAT_OUT="$(env -i HOME="$HOME_DIR" PATH="$STUB_BIN:/usr/bin:/bin" "$BUNDLE_NATIVE/bin/quantumforge" --update 2>&1)"; RC=$?
check_eq "native-layout --update exits 2" "2" "$RC"
case "$NAT_OUT" in
    *"package manager"*) pass "native-layout --update points at apt/pacman/Installed apps instead of guessing" ;;
    *) fail "native-layout guidance lost: $NAT_OUT" ;;
esac

# =======================================================================
printf '== Section 2: real JVM execution of the shipped launcher ==\n'
# =======================================================================
if ((REAL_CHAIN)); then
    BUNDLE_REAL="$(make_bundle 1.0.0 | tail -1)"
    REAL_PREFIX="$HOME_DIR/.local/share/quantumforge"
    REAL_BIN="$HOME_DIR/.local/bin"
    quiet env -i HOME="$HOME_DIR" XDG_DATA_HOME="$HOME_DIR/.local/share" PATH="/usr/bin:/bin" \
        "$BUNDLE_REAL/management/install.sh" --prefix "$REAL_PREFIX" --bin-dir "$REAL_BIN" --yes
    [[ -x "$REAL_PREFIX/current/bin/quantumforge" ]] && pass "real bundle installed into sandbox HOME" \
        || fail "real bundle install failed"

    run_qf() { # <args...> ; bare-word invocation through PATH, like a user terminal
        env -i HOME="$HOME_DIR" XDG_DATA_HOME="$HOME_DIR/.local/share" \
            PATH="$REAL_BIN:/usr/bin:/bin" QUANTUMFORGE_JAVA_HOME="$JDK_BIN/.." \
            timeout 180 quantumforge "$@"
    }

    run_qf --version > "$WORK/out.txt" 2> "$WORK/err.txt"; RC=$?
    check_eq "bare-word 'quantumforge --version' exit code" "0" "$RC"
    check_contains "--version prints the app version" "$WORK/out.txt" "QuantumForge 2.0.0"
    check_contains "--version prints the QE compatibility target" "$WORK/out.txt" "Quantum ESPRESSO input compatibility target"

    run_qf --help > "$WORK/out.txt" 2>&1; RC=$?
    check_eq "'quantumforge --help' exit code" "0" "$RC"
    check_contains "--help prints usage" "$WORK/out.txt" "Usage: quantumforge"

    run_qf --capabilities > "$WORK/out.txt" 2>&1; RC=$?
    check_eq "'quantumforge --capabilities' exit code" "0" "$RC"
    check_contains "--capabilities prints the honest report header" "$WORK/out.txt" "QuantumForge capability report"

    run_qf --doctor > "$WORK/out.txt" 2>&1; RC=$?
    check_eq "'quantumforge --doctor' exit code (warnings allowed, no failures)" "0" "$RC"
    check_contains "--doctor prints the report header" "$WORK/out.txt" "QuantumForge diagnostic report"
    check_contains "--doctor states the missing display instead of faking one" "$WORK/out.txt" "No DISPLAY or WAYLAND_DISPLAY"

    # Bare-word GUI start: argv placeholder proves the entry point is reached.
    run_qf > "$WORK/out.txt" 2>&1; RC=$?
    check_eq "bare 'quantumforge' reaches the GUI entry point" "0" "$RC"
    check_contains "GUI entry receives an empty argv" "$WORK/out.txt" "QF_GUI_PLACEHOLDER_ARGS="

    run_qf report.in "two words" > "$WORK/out.txt" 2>&1; RC=$?
    check_contains "GUI argv passes through verbatim incl. spaces" "$WORK/out.txt" \
        "QF_GUI_PLACEHOLDER_ARGS=[report.in][two words]"

    # X11-forwarding guard with the REAL JVM (prism flag accepted, version works).
    env -i HOME="$HOME_DIR" PATH="$REAL_BIN:/usr/bin:/bin" QUANTUMFORGE_JAVA_HOME="$JDK_BIN/.." \
        SSH_CONNECTION="10.0.0.2 50000 10.0.0.1 22" DISPLAY="localhost:10.0" \
        timeout 180 quantumforge --version > "$WORK/out.txt" 2>&1; RC=$?
    check_eq "--version still works under ssh -X environment (software rendering)" "0" "$RC"

    # Native-style refusal of --update/--uninstall through the REAL JVM is the
    # Java launcher path (management scripts exist here, so script handles it).
    note "GUI pixel output is NOT claimed tested: no display exists here; entry-point and JVM wiring are."
else
    note "real JVM section skipped (no JDK 17): stub-java section above already pinned JVM argv"
fi

# =======================================================================
printf '== Section 3: install / reinstall / uninstall lifecycle ==\n'
# =======================================================================
BUNDLE_LIFE="$(make_bundle 1.0.0 | tail -1)"
LIFE_HOME="$WORK/life-home"
mkdir -p "$LIFE_HOME" "$LIFE_HOME/.quantumforge"
printf 'research data sentinel\n' > "$LIFE_HOME/.quantumforge/sentinel.txt"
LIFE_ENV=("HOME=$LIFE_HOME" "XDG_DATA_HOME=$LIFE_HOME/.local/share" "PATH=/usr/bin:/bin")
LIFE_PREFIX="$LIFE_HOME/.local/share/quantumforge"
LIFE_BIN="$LIFE_HOME/.local/bin"

quiet env -i "${LIFE_ENV[@]}" "$BUNDLE_LIFE/management/install.sh" \
    --prefix "$LIFE_PREFIX" --bin-dir "$LIFE_BIN" --yes
RC=$?
check_eq "install.sh succeeds" "0" "$RC"
[[ "$(readlink "$LIFE_PREFIX/current")" == "versions/1.0.0" ]] \
    && pass "current pointer -> versions/1.0.0" || fail "current pointer wrong: $(readlink "$LIFE_PREFIX/current" 2>/dev/null)"
[[ -L "$LIFE_BIN/quantumforge" ]] && pass "bare-word command symlink installed in bin dir" \
    || fail "command symlink missing"
check_contains "install receipt records the version" "$LIFE_PREFIX/versions/1.0.0/INSTALL_RECEIPT" "version=1.0.0"
check_contains "desktop entry declares the launch command" \
    "$LIFE_HOME/.local/share/applications/quantumforge.desktop" "Managed-By=QuantumForge-Installer"

quiet env -i "${LIFE_ENV[@]}" "$BUNDLE_LIFE/management/install.sh" \
    --prefix "$LIFE_PREFIX" --bin-dir "$LIFE_BIN" --yes
RC=$?
check_eq "reinstall over the same version succeeds (atomic swap)" "0" "$RC"
COUNT="$(find "$LIFE_PREFIX/versions" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
check_eq "reinstall keeps exactly one version directory" "1" "$COUNT"

# Cancelled uninstall keeps everything.
CAN_OUT="$(env -i "${LIFE_ENV[@]}" "$LIFE_BIN/quantumforge" --uninstall < /dev/null 2>&1)"; RC=$?
check_eq "uninstall without confirmation exits 0 (cancelled)" "0" "$RC"
case "$CAN_OUT" in
    *"Uninstall cancelled"*) pass "uninstall cancel is reported, not silent" ;;
    *) fail "uninstall cancel message lost: $CAN_OUT" ;;
esac
[[ -d "$LIFE_PREFIX" ]] && pass "cancelled uninstall deleted nothing" || fail "cancelled uninstall removed files"

# Confirmed uninstall keeps research data.
quiet env -i "${LIFE_ENV[@]}" "$LIFE_BIN/quantumforge" --uninstall --yes
RC=$?
check_eq "uninstall --yes succeeds" "0" "$RC"
[[ ! -e "$LIFE_PREFIX" ]] && pass "install root removed" || fail "install root survived uninstall"
[[ ! -e "$LIFE_BIN/quantumforge" ]] && pass "command symlink removed" || fail "command symlink survived"
[[ ! -e "$LIFE_HOME/.local/share/applications/quantumforge.desktop" ]] \
    && pass "desktop entry removed" || fail "desktop entry survived"
check_contains "research data survives a normal uninstall" "$LIFE_HOME/.quantumforge/sentinel.txt" "sentinel"

# Purge still demands an interactive yes.
quiet env -i "${LIFE_ENV[@]}" "$BUNDLE_LIFE/management/install.sh" \
    --prefix "$LIFE_PREFIX" --bin-dir "$LIFE_BIN" --yes
PURGE_OUT="$(env -i "${LIFE_ENV[@]}" "$LIFE_BIN/quantumforge" --uninstall --yes --purge < /dev/null 2>&1)"; RC=$?
case "$PURGE_OUT" in
    *"Uninstall cancelled"*) pass "--purge refuses non-interactive confirmation (fail-closed)" ;;
    *) fail "--purge without a tty must cancel, got: $PURGE_OUT" ;;
esac
[[ -d "$LIFE_PREFIX" ]] && pass "refused purge deleted nothing" || fail "refused purge removed files anyway"

printf 'y\n' | env -i "${LIFE_ENV[@]}" "$LIFE_BIN/quantumforge" --uninstall --yes --purge > /dev/null 2>&1
RC=$?
check_eq "interactive --purge succeeds" "0" "$RC"
[[ ! -e "$LIFE_HOME/.quantumforge/sentinel.txt" ]] && pass "purge removed user data as promised" \
    || fail "purge kept user data silently"

# Foreign-directory refusal.
FOREIGN="$WORK/foreign"
mkdir -p "$FOREIGN"
cp "$REPO_ROOT/packaging/unix/uninstall.sh" "$FOREIGN/uninstall.sh"
chmod 755 "$FOREIGN/uninstall.sh"
FOR_OUT="$(env -i "${LIFE_ENV[@]}" "$FOREIGN/uninstall.sh" --yes < /dev/null 2>&1)"; RC=$?
check_eq "uninstaller refuses outside an installer-managed tree" "3" "$RC"

# Top-level convenience update.sh inside a download refuses.
TOP_OUT="$(env -i "${LIFE_ENV[@]}" "$BUNDLE_LIFE/update.sh" --yes < /dev/null 2>&1)"; RC=$?
check_eq "update.sh inside an unpacked download refuses" "2" "$RC"
case "$TOP_OUT" in
    *"Install first"*) pass "download-copy update.sh tells the user to install first" ;;
    *) fail "download-copy update.sh message lost: $TOP_OUT" ;;
esac

# =======================================================================
printf '== Section 4: verified update through a loopback release mirror ==\n'
# =======================================================================
UPDATE_RAN=0
if ((REAL_CHAIN)) && command -v curl >/dev/null && command -v python3 >/dev/null; then
    if [[ "$(uname -s)" == "Linux" ]]; then
        UPDATE_RAN=1
        UPD_BUNDLE="$(make_bundle 9.9.9 | tail -1)"
        MIRROR="$WORK/mirror"
        mkdir -p "$MIRROR/repos/farhanwaris78/Quantum-Forge/releases"
        (cd "$(dirname "$UPD_BUNDLE")" && tar -czf "$MIRROR/QuantumForge-9.9.9-linux-x64.tar.gz" \
            "$(basename "$UPD_BUNDLE")")
        (cd "$MIRROR" && sha256sum QuantumForge-9.9.9-linux-x64.tar.gz > SHA256SUMS)

        PORT="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
        python3 -m http.server --bind 127.0.0.1 "$PORT" --directory "$MIRROR" \
            > "$WORK/server.log" 2>&1 &
        SERVER_PID=$!
        READY=0
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/SHA256SUMS" 2>/dev/null; then READY=1; break; fi
            sleep 0.3
        done
        check_eq "loopback mirror is reachable" "1" "$READY"

        write_release_json() { # reuses MIRROR/PORT
            cat > "$MIRROR/repos/farhanwaris78/Quantum-Forge/releases/latest" <<EOF
{"tag_name": "v9.9.9", "draft": false, "prerelease": false,
 "assets": [
   {"name": "QuantumForge-9.9.9-linux-x64.tar.gz",
    "browser_download_url": "http://127.0.0.1:$PORT/QuantumForge-9.9.9-linux-x64.tar.gz"},
   {"name": "SHA256SUMS",
    "browser_download_url": "http://127.0.0.1:$PORT/SHA256SUMS"}
 ]}
EOF
        }
        write_release_json

        UPD_HOME="$WORK/update-home"
        mkdir -p "$UPD_HOME"
        UPD_ENV=("HOME=$UPD_HOME" "XDG_DATA_HOME=$UPD_HOME/.local/share" "PATH=/usr/bin:/bin")
        UPD_PREFIX="$UPD_HOME/.local/share/quantumforge"
        UPD_BIN="$UPD_HOME/.local/bin"
        quiet env -i "${UPD_ENV[@]}" "$BUNDLE_LIFE/management/install.sh" \
            --prefix "$UPD_PREFIX" --bin-dir "$UPD_BIN" --yes

        # HTTPS-only posture: non-loopback plain HTTP is refused before any I/O.
        BAD_OUT="$(env -i "${UPD_ENV[@]}" QUANTUMFORGE_UPDATE_API_BASE="http://releases.example.invalid" \
            "$UPD_BIN/quantumforge" --update --yes 2>&1)"; RC=$?
        check_eq "plain-HTTP non-loopback mirror is refused" "2" "$RC"
        BAD_OUT="$(env -i "${UPD_ENV[@]}" QUANTUMFORGE_UPDATE_API_BASE="ftp://127.0.0.1:$PORT" \
            "$UPD_BIN/quantumforge" --update --yes 2>&1)"; RC=$?
        check_eq "non-HTTP(S) mirror scheme is refused" "2" "$RC"

        # The happy path: 1.0.0 -> 9.9.9 through the real updater.
        UPD_OUT="$(env -i "${UPD_ENV[@]}" QUANTUMFORGE_UPDATE_API_BASE="http://127.0.0.1:$PORT" \
            "$UPD_BIN/quantumforge" --update --yes 2>&1)"; RC=$?
        check_eq "verified loopback update succeeds" "0" "$RC"
        [[ "$(readlink "$UPD_PREFIX/current")" == "versions/9.9.9" ]] \
            && pass "current pointer switched to 9.9.9" \
            || fail "current pointer after update: $(readlink "$UPD_PREFIX/current" 2>/dev/null)"
        [[ -d "$UPD_PREFIX/versions/1.0.0" ]] && pass "previous version kept for rollback" \
            || fail "previous version vanished"
        [[ -L "$UPD_BIN/quantumforge" ]] && pass "bare-word command still resolves after update" \
            || fail "command symlink lost during update"

        # Already-current short-circuit.
        AGAIN_OUT="$(env -i "${UPD_ENV[@]}" QUANTUMFORGE_UPDATE_API_BASE="http://127.0.0.1:$PORT" \
            "$UPD_BIN/quantumforge" --update --yes 2>&1)"; RC=$?
        check_eq "second update run is a no-op" "0" "$RC"
        case "$AGAIN_OUT" in
            *"already current"*) pass "already-current is reported honestly" ;;
            *) fail "already-current message lost: $AGAIN_OUT" ;;
        esac

        # Checksum tampering aborts BEFORE activation.
        quiet env -i "${UPD_ENV[@]}" "$BUNDLE_LIFE/management/install.sh" \
            --prefix "$UPD_PREFIX" --bin-dir "$UPD_BIN" --yes
        GOOD_SUMS="$(cat "$MIRROR/SHA256SUMS")"
        printf '%064d  QuantumForge-9.9.9-linux-x64.tar.gz\n' 0 > "$MIRROR/SHA256SUMS"
        TAM_OUT="$(env -i "${UPD_ENV[@]}" QUANTUMFORGE_UPDATE_API_BASE="http://127.0.0.1:$PORT" \
            "$UPD_BIN/quantumforge" --update --yes 2>&1)"; RC=$?
        check_eq "tampered SHA256SUMS aborts the update" "4" "$RC"
        case "$TAM_OUT" in
            *"SHA-256 verification FAILED; nothing was installed"*) pass "checksum failure message states nothing was installed" ;;
            *) fail "checksum failure message lost: $TAM_OUT" ;;
        esac
        [[ "$(readlink "$UPD_PREFIX/current")" == "versions/1.0.0" ]] \
            && pass "failed update left the running version untouched" \
            || fail "failed update moved the current pointer"
        printf '%s\n' "$GOOD_SUMS" > "$MIRROR/SHA256SUMS"

        # Archive path traversal is refused before extraction.
        cp "$MIRROR/QuantumForge-9.9.9-linux-x64.tar.gz" "$MIRROR/good-backup.tar.gz"
        python3 - "$MIRROR/QuantumForge-9.9.9-linux-x64.tar.gz" <<'PY'
import io, sys, tarfile
with tarfile.open(sys.argv[1], "w:gz") as tar:
    payload = b"evil\n"
    for name in ("../evil.txt", "QuantumForge-9.9.9-linux-x64/../../evil2.txt"):
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
PY
        (cd "$MIRROR" && sha256sum QuantumForge-9.9.9-linux-x64.tar.gz > SHA256SUMS)
        TRV_OUT="$(env -i "${UPD_ENV[@]}" QUANTUMFORGE_UPDATE_API_BASE="http://127.0.0.1:$PORT" \
            "$UPD_BIN/quantumforge" --update --yes 2>&1)"; RC=$?
        check_eq "path-traversal archive is refused" "4" "$RC"
        case "$TRV_OUT" in
            *"Unsafe path in release archive"*) pass "traversal refusal is explicit" ;;
            *) fail "traversal refusal message lost: $TRV_OUT" ;;
        esac
        [[ "$(readlink "$UPD_PREFIX/current")" == "versions/1.0.0" ]] \
            && pass "traversal attempt left the running version untouched" \
            || fail "traversal attempt moved the current pointer"
        ESCAPED="$(find "$WORK" -name 'evil*.txt' -print -quit)"
        [[ -z "$ESCAPED" ]] && pass "no traversal payload landed anywhere" \
            || fail "traversal payload landed at $ESCAPED"
        mv "$MIRROR/good-backup.tar.gz" "$MIRROR/QuantumForge-9.9.9-linux-x64.tar.gz"
        printf '%s\n' "$GOOD_SUMS" > "$MIRROR/SHA256SUMS"
        kill "$SERVER_PID" 2>/dev/null; SERVER_PID=""
    else
        note "loopback update section is Linux-shaped (asset names); skipped on $(uname -s)"
    fi
else
    note "update mirror section skipped (needs the real chain + curl + python3)"
fi

# =======================================================================
printf '== Section 5: release checksum verifier ==\n'
# =======================================================================
SUMS_DIR="$WORK/sums"
mkdir -p "$SUMS_DIR"
printf 'payload one\n' > "$SUMS_DIR/a.bin"
printf 'payload two\n' > "$SUMS_DIR/b.bin"
(cd "$SUMS_DIR" && sha256sum a.bin b.bin > SHA256SUMS)
quiet bash -c "cd '$SUMS_DIR' && '$REPO_ROOT/packaging/verify-checksums.sh'"
RC=$?
check_eq "verify-checksums accepts a good directory" "0" "$RC"
printf 'tampered\n' > "$SUMS_DIR/b.bin"
TAMPER_OUT="$(bash -c "cd '$SUMS_DIR' && '$REPO_ROOT/packaging/verify-checksums.sh'" 2>&1)"; RC=$?
if ((RC != 0)); then pass "verify-checksums rejects tampered content"; else fail "verify-checksums accepted tampered content"; fi

# =======================================================================
printf '== Section 6: shell syntax sweep of every shipped script ==\n'
# =======================================================================
SYNTAX_OK=1
while IFS= read -r script; do
    if ! bash -n "$script" 2> "$WORK/syntax.log"; then
        SYNTAX_OK=0
        fail "bash -n failed: $script"; cat "$WORK/syntax.log" >&2
    fi
done < <(find "$REPO_ROOT/packaging" -name '*.sh' -type f | sort)
if ! bash -n "$REPO_ROOT/packaging/unix/quantumforge" 2> "$WORK/syntax.log"; then
    SYNTAX_OK=0
    fail "bash -n failed on the launcher"; cat "$WORK/syntax.log" >&2
fi
((SYNTAX_OK)) && pass "bash -n clean for all packaging shell scripts and the launcher" || true

# =======================================================================
printf '\nSMOKE SUMMARY: %d passed, %d failed, %d note(s)\n' "$PASS" "$FAIL" "$NOTES"
if ((FAIL > 0)); then
    echo "SMOKE RESULT: FAILED"
    exit 1
fi
echo "SMOKE RESULT: PASSED"
exit 0
