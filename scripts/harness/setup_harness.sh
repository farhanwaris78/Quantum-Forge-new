#!/bin/bash
# QuantumForge headless javac harness bootstrap.
#
# The project ships JavaFX GUI sources that cannot compile headlessly; this
# script compiles every src file that does NOT transitively need JavaFX (the
# iterative taint prune), every test that resolves against that class set, the
# mini-JUnit5 surface, and the harness-only QEInput/QESCFInput structural
# stubs for the schema adapter layer. Wholly ephemeral: everything lands under
# ${QF_HARNESS_TMP:-/tmp/qfharness} and can be rebuilt any time.
#
# Usage:
#   scripts/harness/setup_harness.sh          # clone JDK17 if needed + compile
#   scripts/harness/run_tests.sh [runlist]    # execute a runlist with MiniRunner
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HH="$ROOT/scripts/harness"
TMPROOT="${QF_HARNESS_TMP:-/tmp/qfharness}"
JDK="$TMPROOT/jdk17pre/linux-x86"
mkdir -p "$TMPROOT/work" "$TMPROOT/qfclasses" "$TMPROOT/testclasses" \
         "$TMPROOT/newcls" "$TMPROOT/newtests" "$TMPROOT/schemacls" \
         "$TMPROOT/schematests" "$TMPROOT/stubcls" "$TMPROOT/probe"
# Clean every class bucket: stale class files from earlier rounds (or manual
# per-batch compiles in newcls/newtests) must never shadow a fresh build.
for d in qfclasses testclasses newcls newtests schemacls schematests stubcls; do
    find "$TMPROOT/$d" -name '*.class' -delete 2>/dev/null
done

if [ ! -x "$JDK/bin/javac" ]; then
    echo "cloning JDK17 prebuilts (sparse linux-x86 only)..."
    rm -rf "$TMPROOT/jdk17pre"
    GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/msft-mirror-aosp/platform.prebuilts.jdk.jdk17 "$TMPROOT/jdk17pre"
    (cd "$TMPROOT/jdk17pre" && git sparse-checkout set linux-x86)
    chmod -R +x "$TMPROOT/jdk17pre/linux-x86/bin"
fi
export PATH="$JDK/bin:$PATH"
javac -version

LIB="$ROOT/lib/exp4j-0.4.6.jar:$ROOT/lib/gson-2.6.1.jar:$ROOT/lib/jcodec-0.2.0.jar:$ROOT/lib/jcodec-javase-0.2.0.jar:$ROOT/lib/jsch-0.1.54.jar"

echo "compiling mini-junit stub + MiniRunner..."
find "$TMPROOT/stubcls" -name '*.class' -delete 2>/dev/null
javac -d "$TMPROOT/stubcls" $(find "$HH/stubsrc" -name '*.java') "$HH/minijunit/MiniRunner.java" || exit 1

echo "compiling main sources (iterative JavaFX taint prune)..."
EXCL="$TMPROOT/excluded.txt"
: > "$EXCL"
cd "$ROOT"
for round in 1 2 3 4 5 6 7 8 9 10 11 12; do
    find src -name '*.java' | sort > "$TMPROOT/work/all.txt"
    grep -vxFf "$EXCL" "$TMPROOT/work/all.txt" > "$TMPROOT/work/candidates.txt" || true
    ERR="$TMPROOT/work/errors.$round.txt"
    javac -nowarn -encoding UTF-8 -Xmaxerrs 5000 -cp "$LIB" -d "$TMPROOT/qfclasses" @"$TMPROOT/work/candidates.txt" 2> "$ERR"
    if [ ! -s "$ERR" ]; then echo "main: clean in round $round"; break; fi
    grep -oP '^src/[^\s:]+\.java' "$ERR" | sort -u > "$TMPROOT/work/badfiles.txt" || true
    grep -oP 'symbol:\s+(class|interface|enum|variable)\s+\K[A-Za-z_][A-Za-z0-9_]*' "$ERR" | sort -u > "$TMPROOT/work/missing.txt" || true
    : > "$TMPROOT/work/newexcl.txt"
    while read -r sym; do find src -name "$sym.java" >> "$TMPROOT/work/newexcl.txt"; done < "$TMPROOT/work/missing.txt"
    while read -r f; do echo "$f" >> "$TMPROOT/work/newexcl.txt"; done < "$TMPROOT/work/badfiles.txt"
    sort -u "$TMPROOT/work/newexcl.txt" | sed '/^$/d' > "$TMPROOT/work/newexcl.sorted.txt"
    NEWN=$(comm -23 "$TMPROOT/work/newexcl.sorted.txt" "$EXCL" | wc -l)
    echo "main round $round: $(grep -c ': error:' "$ERR") errors, $NEWN new exclusions"
    if [ "$NEWN" -eq 0 ]; then echo "FIXPOINT main"; grep -m5 ': error:' "$ERR"; break; fi
    cat "$TMPROOT/work/newexcl.sorted.txt" >> "$EXCL"
    sort -u "$EXCL" > "$TMPROOT/work/e.new" && mv "$TMPROOT/work/e.new" "$EXCL"
done

echo "compiling schema adapter + typed deck-planner layer (harness-only QEInput stubs)..."
javac -nowarn -encoding UTF-8 -cp "$TMPROOT/qfclasses" -d "$TMPROOT/schemacls" \
    "$HH/qestub/quantumforge/input/QEInput.java" \
    "$HH/qestub/quantumforge/input/QESCFInput.java" \
    "$ROOT/src/quantumforge/input/validation/QESchemaValidator.java" \
    "$ROOT/src/quantumforge/input/PhInputPlanner.java" \
    "$ROOT/src/quantumforge/input/QEHubbardPlanner.java" \
    "$ROOT/src/quantumforge/input/CpInputPlanner.java" || exit 1

echo "compiling tests (iterative prune)..."
TEXCL="$TMPROOT/test_excluded.txt"
: > "$TEXCL"
CP="$TMPROOT/qfclasses:$TMPROOT/stubcls:$LIB"
for round in 1 2 3 4 5 6 7 8 9 10; do
    find tests/java -name '*.java' | sort > "$TMPROOT/work/tall.txt"
    grep -vxFf "$TEXCL" "$TMPROOT/work/tall.txt" > "$TMPROOT/work/tcandidates.txt" || true
    ERR="$TMPROOT/work/terrors.$round.txt"
    javac -nowarn -encoding UTF-8 -Xmaxerrs 5000 -cp "$CP" -d "$TMPROOT/testclasses" @"$TMPROOT/work/tcandidates.txt" 2> "$ERR"
    if [ ! -s "$ERR" ]; then echo "tests: clean in round $round"; break; fi
    grep -oP '^tests/java/[^\s:]+\.java' "$ERR" | sort -u > "$TMPROOT/work/tbad.txt" || true
    grep -oP 'symbol:\s+(class|interface|enum|variable)\s+\K[A-Za-z_][A-Za-z0-9_]*' "$ERR" | sort -u > "$TMPROOT/work/tmissing.txt" || true
    : > "$TMPROOT/work/tnew.txt"
    while read -r sym; do find tests/java -name "$sym.java" >> "$TMPROOT/work/tnew.txt"; done < "$TMPROOT/work/tmissing.txt"
    while read -r f; do echo "$f" >> "$TMPROOT/work/tnew.txt"; done < "$TMPROOT/work/tbad.txt"
    sort -u "$TMPROOT/work/tnew.txt" | sed '/^$/d' > "$TMPROOT/work/tnew.sorted.txt"
    NEWN=$(comm -23 "$TMPROOT/work/tnew.sorted.txt" "$TEXCL" | wc -l)
    echo "tests round $round: $(grep -c ': error:' "$ERR") errors, $NEWN new exclusions"
    if [ "$NEWN" -eq 0 ]; then echo "FIXPOINT tests"; grep -m5 ': error:' "$ERR"; break; fi
    cat "$TMPROOT/work/tnew.sorted.txt" >> "$TEXCL"
    sort -u "$TEXCL" > "$TMPROOT/work/te.new" && mv "$TMPROOT/work/te.new" "$TEXCL"
done

echo "compiling schema + deck-planner tests against stub layer..."
javac -nowarn -encoding UTF-8 -cp "$TMPROOT/newcls:$TMPROOT/schemacls:$TMPROOT/qfclasses:$TMPROOT/stubcls:$TMPROOT/testclasses" \
    -d "$TMPROOT/schematests" \
    "$ROOT/tests/java/quantumforge/input/validation/QESchemaValidatorTest.java" \
    "$ROOT/tests/java/quantumforge/input/PhInputPlannerTest.java" \
    "$ROOT/tests/java/quantumforge/input/QEHubbardPlannerTest.java" \
    "$ROOT/tests/java/quantumforge/input/CpInputPlannerTest.java" \
    "$ROOT/tests/java/quantumforge/input/validation/QECardAuditTest.java" \
    "$ROOT/tests/java/quantumforge/input/schema/QECardSchemaTest.java" \
    "$ROOT/tests/java/quantumforge/input/validation/QEDeckDialectTest.java" \
    "$ROOT/tests/java/quantumforge/input/schema/QEAuxSchemaTest.java" \
    "$ROOT/tests/java/quantumforge/input/validation/QEAuxDeckAuditTest.java" \
    "$ROOT/tests/java/quantumforge/input/QEAuxDeckPlannerTest.java" || exit 1

{ find "$TMPROOT/testclasses" -name '*.class' | sed "s|$TMPROOT/testclasses/||; s|\.class$||; s|/|.|g; s|\$.*$||" | sort -u
  echo quantumforge.input.validation.QESchemaValidatorTest
  echo quantumforge.input.PhInputPlannerTest
  echo quantumforge.input.QEHubbardPlannerTest
  echo quantumforge.input.CpInputPlannerTest
  echo quantumforge.input.validation.QECardAuditTest
  echo quantumforge.input.schema.QECardSchemaTest
  echo quantumforge.input.validation.QEDeckDialectTest
  echo quantumforge.input.schema.QEAuxSchemaTest
  echo quantumforge.input.validation.QEAuxDeckAuditTest
  echo quantumforge.input.QEAuxDeckPlannerTest; } | sort -u > "$TMPROOT/run_all.txt"
echo "setup complete: $(find $TMPROOT/qfclasses -name '*.class' | wc -l) main classes, $(wc -l < $TMPROOT/run_all.txt) runnable test classes"
