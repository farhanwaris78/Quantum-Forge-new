#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Capture a real Quantum ESPRESSO run and stage it as QuantumForge fixtures.
#
# The golden fixtures in tests/fixtures/qe/golden/ are format-faithful but
# synthetic (written from QE's Fortran, never captured). The single
# highest-value data contribution is one real run of pw.x + bands.x +
# matdyn.x + projwfc.x on a small system - silicon is perfect. This script
# runs that small system, then stages every output into
# tests/fixtures/qe/real/ under the pinned names the parsers and the harness
# expect, and appends the provenance rows.
#
# Requires: a working Quantum ESPRESSO installation (pw.x, bands.x, matdyn.x,
# projwfc.x on PATH or via $QE_BIN), a silicon pseudopotential, and gnuplot
# (matdyn.x writes .freq.gp; the gnuplot files are checked in as-is).
#
# Usage:
#   QE_BIN=/path/to/bin ./tools/capture_qe_run.sh [workdir]
#
# The workdir defaults to a fresh directory under /tmp. Everything is staged
# into the repo's tests/fixtures/qe/real/ with the PROVENANCE.md notes
# appended (the SHA-256 prefixes are computed here). Review the diff, then
# commit.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REAL_DIR="$REPO_ROOT/tests/fixtures/qe/real"
QE_BIN="${QE_BIN:-}"
if [ -n "$QE_BIN" ]; then
    export PATH="$QE_BIN:$PATH"
fi
for tool in pw.x bands.x matdyn.x projwfc.x; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "error: $tool not found on PATH (set QE_BIN=/path/to/bin)" >&2
        exit 1
    fi
done

WORK="${1:-$(mktemp -d /tmp/qf-capture.XXXXXX)}"
mkdir -p "$WORK"
cd "$WORK"
echo "workdir: $WORK"

# A tiny silicon SCF with a band path and a phonon q-path. 2x2x2 k-mesh is
# enough; keep the runs seconds-to-a-minute, not hours. The exact numbers do
# not matter - the files are captured for their FORMAT, and the harness pins
# only the invariants (iteration counts, '!' energies, row counts).
cat > si.scf.in <<'EOF'
&CONTROL
   calculation = 'scf'
   prefix = 'si'
   outdir = './'
   pseudo_dir = './'
   verbosity = 'high'
/
&SYSTEM
   ibrav = 2
   celldm(1) = 10.20
   nat = 2
   ntyp = 1
   ecutwfc = 24.0
   ecutrho = 240.0
   occupations = 'smearing'
   smearing = 'gaussian'
   degauss = 0.02
/
&ELECTRONS
   conv_thr = 1.0d-8
   mixing_beta = 0.7
/
ATOMIC_SPECIES
  Si 28.0855 Si.UPF
ATOMIC_POSITIONS alat
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
K_POINTS automatic
  4 4 4 0 0 0
EOF

# The pseudopotential must be present. Try common names; fail with a pointer
# if none matches.
PSEUDO=""
for candidate in Si.UPF Si.pz-vbc.UPF Si.pbe-n-rrkjus_psl.1.0.0.UPF; do
    if [ -f "$candidate" ]; then PSEUDO="$candidate"; break; fi
done
if [ -z "$PSEUDO" ]; then
    echo "error: copy a silicon UPF into $WORK as Si.UPF (any Si pseudopotential works)" >&2
    exit 1
fi
sed -i "s/Si.UPF/$PSEUDO/" si.scf.in

pw.x -in si.scf.in > pwscf_si_scf_captured.out 2>&1

# projwfc.x needs the SCF charge; write its input and run it.
cat > projwfc.in <<'EOF'
&PROJWFC
   prefix = 'si'
   outdir = './'
   ngauss = 1
   degauss = 0.02
   DeltaE = 0.1
/
EOF
projwfc.x -in projwfc.in > projwfc_si_captured.out 2>&1

# bands.x: non-self-consistent along a high-symmetry path.
cat > si.bands.in <<'EOF'
&CONTROL
   calculation = 'bands'
   prefix = 'si'
   outdir = './'
   pseudo_dir = './'
   verbosity = 'high'
/
&SYSTEM
   ibrav = 2
   celldm(1) = 10.20
   nat = 2
   ntyp = 1
   ecutwfc = 24.0
   ecutrho = 240.0
/
&ELECTRONS
   conv_thr = 1.0d-8
/
ATOMIC_SPECIES
  Si 28.0855 Si.UPF
ATOMIC_POSITIONS alat
  Si 0.00 0.00 0.00
  Si 0.25 0.25 0.25
K_POINTS crystal_b
  3
  0.000 0.000 0.000 20
  0.500 0.500 0.500 20
  0.750 0.500 0.250 20
EOF
sed -i "s/Si.UPF/$PSEUDO/" si.bands.in
pw.x -in si.bands.in > pwscf_si_bands_captured.out 2>&1
bands.x -in si.bands.in > bands_si_captured.out 2>&1

# matdyn.x: phonons from a simple force-constants run is heavier; capture what
# the parser consumes - matdyn.freq and matdyn.freq.gp - from any small
# phonon run. If you already have a q2r/matdyn pair, point this at it.
if command -v ph.x >/dev/null 2>&1 && command -v q2r.x >/dev/null 2>&1; then
    echo "ph.x/q2r.x found - capturing a phonon path too (this takes longer)."
    cat > si.ph.in <<'EOF'
phonons of Si
&INPUTPH
   prefix = 'si'
   outdir = './'
   fildyn = 'si.dyn'
   tr2_ph = 1.0d-12
   ldisp = .true.
   nq1 = 2
   nq2 = 2
   nq3 = 2
/
EOF
    ph.x -in si.ph.in > ph_si_captured.out 2>&1 || echo "warning: ph.x failed; skipping the phonon capture"
    if [ -f si.dyn1 ]; then
        cat > q2r.in <<'EOF'
&INPUT
   fildyn = 'si.dyn'
   flfrc = 'si.fc'
/
EOF
        q2r.x -in q2r.in > q2r_si_captured.out 2>&1
        cat > matdyn.in <<'EOF'
&INPUT
   flfrc = 'si.fc'
   flfrq = 'matdyn.freq'
   q_in_band_form = .true.
/
2
  0.000 0.000 0.000 20
  0.500 0.500 0.500 20
EOF
        matdyn.x -in matdyn.in > matdyn_si_captured.out 2>&1
    fi
fi

# ---------------------------------------------------------------------------
# Stage: copy under the pinned fixture names and append provenance.
# ---------------------------------------------------------------------------
stage() {
    local src="$1" dst="$2"
    if [ -f "$src" ]; then
        cp "$src" "$REAL_DIR/$dst"
        local sha
        sha=$(sha256sum "$REAL_DIR/$dst" | cut -c1-16)
        echo "staged $dst ($sha)"
    else
        echo "warning: $src missing; $dst not staged"
    fi
}

stage pwscf_si_scf_captured.out      pwscf_si_scf_captured.out
stage projwfc_si_captured.out        projwfc_si_captured.out
stage pwscf_si_bands_captured.out    pwscf_si_bands_captured.out
stage bands_si_captured.out          bands_si_captured.out
stage bands.dat.gnu                  bands_si_captured.dat.gnu
stage matdyn.freq                    matdyn_si_captured.freq
stage matdyn.freq.gp                 matdyn_si_captured.freq.gp

cat >> "$REAL_DIR/PROVENANCE.md" <<'EOF'

## Captured run: <date>

Run performed with <QE version> on <host> using tools/capture_qe_run.sh.
Files: pwscf_si_scf_captured.out, projwfc_si_captured.out,
pwscf_si_bands_captured.out, bands_si_captured.out, bands_si_captured.dat.gnu,
matdyn_si_captured.freq, matdyn_si_captured.freq.gp.
EOF
echo
echo "Review with: git diff --stat"
echo "Commit with: git add tests/fixtures/qe/real && git commit"
