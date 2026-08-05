#!/bin/bash
# Runs a MiniRunner runlist against the headless harness classes.
# Usage: scripts/harness/run_tests.sh [runlist-file]
# Default runlist: ${QF_HARNESS_TMP:-/tmp/qfharness}/run_all.txt
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMPROOT="${QF_HARNESS_TMP:-/tmp/qfharness}"
RUNLIST="${1:-$TMPROOT/run_all.txt}"
export PATH="$TMPROOT/jdk17pre/linux-x86/bin:$PATH"
cd "$ROOT"
java -Xmx1g -cp "$TMPROOT/newtests:$TMPROOT/schematests:$TMPROOT/schemacls:$TMPROOT/newcls:$TMPROOT/testclasses:$TMPROOT/qfclasses:$TMPROOT/stubcls:lib/exp4j-0.4.6.jar:lib/gson-2.6.1.jar:lib/jcodec-0.2.0.jar:lib/jcodec-javase-0.2.0.jar:lib/jsch-0.1.54.jar" \
    minijunit.MiniRunner "$RUNLIST"
