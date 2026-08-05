#!/usr/bin/env bash
# Capture a real thermo_pw run's data files for the fixture corpus.
#
# Suggestion 18.33/18.34: the VASP/QE parsers are pinned to real captured
# files; the thermo_pw parsers are pinned to the upstream examples' reference
# outputs (tests/fixtures/thermo_pw/real). This script lets anyone with a
# thermo_pw build (make join_qe + make thermo_pw inside QE) capture THEIR
# own run's outputs, so the corpus also carries non-upstream evidence.
#
# Usage:
#   tools/capture_thermo_pw_run.sh WORKDIR OUTDIR [LABEL]
#     WORKDIR : directory where thermo_pw.x already ran (has thermo_control,
#               energy_files/, anhar_files/, therm_files/, ...)
#     OUTDIR  : where the captured files land (default tests/fixtures/thermo_pw/real)
#     LABEL   : a short tag appended to the copied names (default 'run')
#
# The script copies the data files thermo_pw writes, appends the provenance
# rows to tests/fixtures/thermo_pw/real/PROVENANCE.md, and prints a summary.
# It never runs thermo_pw - it captures what is already there.

set -euo pipefail

WORKDIR="${1:-}"
OUTDIR="${2:-tests/fixtures/thermo_pw/real}"
LABEL="${3:-run}"

if [ -z "$WORKDIR" ] || [ ! -d "$WORKDIR" ]; then
    echo "usage: $0 WORKDIR OUTDIR [LABEL]" >&2
    echo "WORKDIR must be a directory where thermo_pw.x has run." >&2
    exit 2
fi
mkdir -p "$OUTDIR"

capture() {
    local src="$1"
    local base="$2"
    if [ -f "$WORKDIR/$src" ]; then
        cp "$WORKDIR/$src" "$OUTDIR/${base}.${LABEL}"
        echo "  captured $src -> ${base}.${LABEL}"
    fi
}

echo "Capturing thermo_pw data files from $WORKDIR (label: $LABEL)"
capture energy_files/output_ev.dat           output_ev
capture energy_files/output_keconv.dat1/output_keconv.dat output_keconv
capture energy_files/output_nkconv.dat1/output_nkconv.dat output_nkconv
capture anhar_files/output_anhar.dat          output_anhar
capture anhar_files/output_elanhar.dat        output_elanhar
capture anhar_files/output_grun.dat           output_grun
capture anhar_files/output_pgrun.dat          output_pgrun
capture therm_files/output_eldos.dat          output_eldos
capture therm_files/output_eltherm.dat        output_eltherm
capture therm_files/output_therm.dat.g1       output_therm
capture elastic_constants/output_el_cons.dat.g1 output_el_cons

echo
echo "Files captured under $OUTDIR. Add a provenance block to"
echo "tests/fixtures/thermo_pw/real/PROVENANCE.md for each file: source"
echo "run, what= task, date, thermo_pw version (the run output header),"
echo "and the command used."
