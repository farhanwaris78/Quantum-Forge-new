#!/usr/bin/env python3
"""Lightweight offline validation of golden QE fixtures and analyzer contracts.

Used when a full JDK/Maven toolchain is unavailable. This is not a substitute
for `mvn verify`, but it catches fixture/regex regressions immediately.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "qe"
ERRORS: list[str] = []


def error(msg: str) -> None:
    ERRORS.append(msg)


def read(name: str) -> str:
    path = FIX / name
    if not path.is_file():
        error(f"missing fixture {name}")
        return ""
    return path.read_text(encoding="utf-8")


TOTAL_BANG = re.compile(
    r"^\s*!\s*total energy\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s*Ry",
    re.I | re.M,
)
TOTAL_PLAIN = re.compile(
    r"^\s*total energy\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)\s*Ry",
    re.I | re.M,
)
NOT_CONV = re.compile(r"convergence NOT achieved", re.I)
BFGS = re.compile(r"bfgs converged in\s+\d+\s+scf cycles|End final coordinates", re.I)
MISSING_PSEUDO = re.compile(
    r"Error in routine read_pseudopot|file .*\.UPF not found", re.I
)
HIGH_SYM = re.compile(r"high-symmetry point:")

# Occupation-level needles, mirrored VERBATIM from the owning class
# src/quantumforge/run/parser/OccupationLevelsParser.java (PAIR / SINGLE).
# The Java parser is the single owner; if its grammar changes this mirror
# must change in the same commit or the class-matrix pins below drift.
OCC_PAIR = re.compile(
    r"highest occupied, lowest unoccupied level \(ev\):\s*(\S+)\s+(\S+)"
)
OCC_SINGLE = re.compile(r"highest occupied level \(ev\):\s*(\S+)")


def scf_iterations(text: str) -> list[tuple[float, bool]]:
    rows: list[tuple[float, bool]] = []
    for line in text.splitlines():
        m = TOTAL_BANG.match(line)
        if m:
            rows.append((float(m.group(1).replace("D", "E").replace("d", "e")), True))
            continue
        m = TOTAL_PLAIN.match(line)
        if m:
            rows.append((float(m.group(1).replace("D", "E").replace("d", "e")), False))
    return rows


GOLDEN = FIX / "golden"

REQUIRED_GOLDEN_CASES = [
    "si_bulk_scf",
    "mgo_insulator_scf",
    "fe_spin_metal_scf",
    "slab_vacuum_scf",
    "hubbard_u_scf",
]


def _parse_expect(path: Path) -> dict:
    kv = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        kv[key.strip()] = value.strip()
    return kv


def check_golden_fixtures() -> None:
    """Validate the QE golden triples offline.

    Mirrors the invariants QeGoldenFixtureTest asserts in Java, so a broken
    fixture is caught by the dependency-free CI step too:
      * every required case ships .in / .out / .expect,
      * the declared final energy IS the '!' total energy line,
      * gap == LUMO - HOMO, and internal energy == F - (-TS),
      * the declared iteration count matches the log,
      * provenance is documented.
    """
    if not GOLDEN.is_dir():
        error("missing tests/fixtures/qe/golden directory")
        return

    if not (GOLDEN / "PROVENANCE.md").is_file():
        error("golden fixtures must ship PROVENANCE.md")

    for case in REQUIRED_GOLDEN_CASES:
        for ext in (".in", ".out", ".expect"):
            if not (GOLDEN / (case + ext)).is_file():
                error(f"golden case {case} is missing {ext}")

    for expect_path in sorted(GOLDEN.glob("*.expect")):
        case = expect_path.stem
        out_path = GOLDEN / (case + ".out")
        if not out_path.is_file():
            error(f"golden case {case}: no .out beside .expect")
            continue

        kv = _parse_expect(expect_path)
        out = out_path.read_text(encoding="utf-8")

        bang = TOTAL_BANG.findall(out)
        if "out.finalEnergyRy" in kv:
            if not bang:
                error(f"golden case {case}: no '!' total energy line in .out")
            elif abs(float(bang[-1]) - float(kv["out.finalEnergyRy"])) > 1e-9:
                error(f"golden case {case}: declared finalEnergyRy "
                      f"{kv['out.finalEnergyRy']} != '!' line {bang[-1]}")

        if "out.iterations" in kv:
            actual = len(re.findall(r"iteration #", out))
            if actual != int(kv["out.iterations"]):
                error(f"golden case {case}: declared {kv['out.iterations']} "
                      f"iterations but .out has {actual}")

        if {"out.homoEv", "out.lumoEv", "out.gapEv"} <= kv.keys():
            gap = float(kv["out.lumoEv"]) - float(kv["out.homoEv"])
            if abs(gap - float(kv["out.gapEv"])) > 1e-4:
                error(f"golden case {case}: gap {gap:.4f} != declared "
                      f"{kv['out.gapEv']} (must equal LUMO - HOMO)")

        if {"out.internalEnergyRy", "out.smearingContribRy",
                "out.finalEnergyRy"} <= kv.keys():
            internal = float(kv["out.finalEnergyRy"]) - float(kv["out.smearingContribRy"])
            if abs(internal - float(kv["out.internalEnergyRy"])) > 1e-6:
                error(f"golden case {case}: F - (-TS) = {internal:.8f} != declared "
                      f"internal energy {kv['out.internalEnergyRy']}")

        for key in ("out.smearingContribRy", "out.fermiEv", "out.totalForceRyAu"):
            if key not in kv:
                continue
            needle = {
                "out.smearingContribRy": r"smearing contrib\. \(-TS\)\s*=\s*(\S+)\s*Ry",
                "out.fermiEv": r"the Fermi energy is\s*(\S+)\s*ev",
                "out.totalForceRyAu": r"Total force\s*=\s*(\S+)",
            }[key]
            found = re.findall(needle, out)
            if not found:
                error(f"golden case {case}: {key} declared but not present in .out")
            elif abs(float(found[-1]) - float(kv[key])) > 1e-6:
                error(f"golden case {case}: {key} declared {kv[key]} != {found[-1]}")


# --- Real captured outputs (tests/fixtures/qe/real) --------------------------
# These are byte-for-byte copies of QE's own reference outputs (see
# real/PROVENANCE.md: QEF/q-e@qe-7.5, commit 770a0b2). The invariants below
# mirror the Java tests (RealCapturedOutputTest, QEPhononFreqParserTest,
# PseudoPotentialUpfV1HeaderTest), so a damaged copy is caught offline too.

REAL = FIX / "real"
REAL_FREQ_NUM = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][+-]?\d+)?")


def real_freq_rows(name: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in (REAL / name).read_text(encoding="utf-8").splitlines():
        trim = line.strip()
        if not trim or trim.startswith("#") or trim.startswith("@"):
            continue
        nums = [float(x) for x in REAL_FREQ_NUM.findall(trim)]
        if len(nums) >= 2:
            rows.append(nums)
    return rows


def check_real_fixtures() -> None:
    if not (REAL / "PROVENANCE.md").is_file():
        error("real fixture directory must ship PROVENANCE.md")
        return

    def real(name: str) -> str:
        path = REAL / name
        if not path.is_file():
            error(f"missing real fixture {name}")
            return ""
        return path.read_text(encoding="utf-8")

    # pw.x SCF outputs: real iteration counts and '!' energies.
    scf_cases = {
        # name: (energy lines, final '!' energy Ry, Fermi eV or None)
        "pwscf_si_scf_v6.out": (6, "-15.84452726", None),
        "pwscf_cu_scf_v6.out": (7, "-87.84037038", "14.5033"),
        "pwscf_ni_scf_v6.out": (9, "-85.72256763", "15.2989"),
    }
    for name, (expected_iters, expected_bang, fermi) in scf_cases.items():
        text = real(name)
        if not text:
            continue
        rows = scf_iterations(text)
        if len(rows) != expected_iters:
            error(f"real fixture {name}: expected {expected_iters} energy lines, "
                  f"got {len(rows)}")
        if not rows or not rows[-1][1]:
            error(f"real fixture {name}: final line is not a '!' converged line")
        elif abs(float(rows[-1][0]) - float(expected_bang)) > 1e-8:
            error(f"real fixture {name}: final energy {rows[-1][0]} != {expected_bang}")
        if NOT_CONV.search(text):
            error(f"real fixture {name} unexpectedly not-converged")
        if "JOB DONE" not in text:
            error(f"real fixture {name} missing JOB DONE")
        if fermi is not None:
            hits = re.findall(r"the Fermi energy is\s*(\S+)\s*ev", text, re.I)
            if not hits or abs(float(hits[-1]) - float(fermi)) > 1e-4:
                error(f"real fixture {name}: Fermi energy {hits} != {fermi}")

    relax = real("pwscf_al_relax_v6.out")
    if relax:
        if not re.search(r"bfgs converged in\s+\d+\s+scf cycles", relax, re.I):
            error("real relax fixture missing bfgs-converged marker")
        if "JOB DONE" not in relax:
            error("real relax fixture missing JOB DONE")
        if len(scf_iterations(relax)) != 81:
            error(f"real relax fixture: expected 81 SCF energy lines across 9 BFGS "
                  f"steps, got {len(scf_iterations(relax))}")

    # matdyn.freq (flfrq layout): '&plot' header and number count.
    flfrq = real("matdyn_alas.freq")
    if flfrq:
        header = re.search(r"&plot\s+nbnd=\s*(\d+)\s*,\s*nks=\s*(\d+)", flfrq, re.I)
        if not header or (header.group(1), header.group(2)) != ("6", "16"):
            error("real flfrq fixture: expected '&plot nbnd=6, nks=16' header")
        body = flfrq.splitlines()[1:]
        values = REAL_FREQ_NUM.findall(" ".join(body))
        if len(values) != 144:
            error(f"real flfrq fixture: expected 144 numbers after the header, "
                  f"got {len(values)}")

    # matdyn.freq.gp sidecars: row/mode counts, monotonic path, imaginary modes.
    gp_cases = {
        "matdyn_alas.freq.gp": (16, 6),
        "matdyn_al.freq.gp": (161, 3),
        "matdyn_bn.freq.gp": (91, 6),
    }
    for name, (expected_rows, expected_modes) in gp_cases.items():
        rows = real_freq_rows(name)
        if len(rows) != expected_rows:
            error(f"real fixture {name}: expected {expected_rows} q-path rows, "
                  f"got {len(rows)}")
            continue
        if len(rows[0]) - 1 != expected_modes:
            error(f"real fixture {name}: expected {expected_modes} modes, "
                  f"got {len(rows[0]) - 1}")
        if any(rows[i][0] > rows[i + 1][0] for i in range(len(rows) - 1)):
            error(f"real fixture {name}: path length is not monotonic")
    bn_imag = [v for row in real_freq_rows("matdyn_bn.freq.gp")
               for v in row[1:] if v < -0.1]
    if len(bn_imag) < 1 or min(bn_imag) > -3.6074:
        error("real BN fixture must carry imaginary modes (most negative -3.6074)")

    # The McMillan file is a gnuplot SCRIPT, not data; it must contain text.
    mcm = real("aluminum.McMillan.gp")
    if mcm and re.search(r"[A-Za-z]", mcm) is None:
        error("aluminum.McMillan.gp must contain non-numeric text (it is a script)")

    # Real plotbands.x output: 328 two-column rows, 8 blank-line-separated
    # bands of 41 points, k from 0.0 to 2.832 (closed high-symmetry path).
    bands = real("bands_pbe.dat.gnu")
    if bands:
        rows = []
        for line in bands.splitlines():
            t = line.strip()
            if not t or t.startswith("#") or t.startswith("@"):
                continue
            nums = REAL_FREQ_NUM.findall(t)
            if len(nums) >= 2:
                rows.append([float(x) for x in nums[:2]])
        if len(rows) != 328:
            error(f"real bands fixture: expected 328 data rows, got {len(rows)}")
        elif rows[0][0] != 0.0 or abs(rows[-1][0] - 2.832) > 1.0e-3:
            error(f"real bands fixture: k-path must run 0.0 .. 2.832, "
                  f"got {rows[0][0]} .. {rows[-1][0]}")
        if bands.count("\n\n") != 8:
            error(f"real bands fixture: expected 8 blank-line separators, "
                  f"got {bands.count(chr(10) + chr(10))}")

    # Real spin-polarised projwfc.x PDOS files (PP/examples/example02, Ni):
    # header-driven column resolution, 202 rows, E 5.0 .. 25.1 eV.
    for name in ("ni.pdos_atm#1(Ni)_wfc#1(s)", "ni.pdos_atm#1(Ni)_wfc#2(d)"):
        text = real(name)
        if not text:
            continue
        header = next((l for l in text.splitlines() if l.strip().startswith("#")), "")
        if "ldosup" not in header or "pdosup" not in header:
            error(f"real PDOS fixture {name}: unexpected header {header[:60]}")
        rows = []
        for line in text.splitlines():
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            toks = [float(x.replace("D", "E")) for x in REAL_FREQ_NUM.findall(t)]
            if len(toks) >= 2:
                rows.append(toks)
        if len(rows) != 202:
            error(f"real PDOS fixture {name}: expected 202 rows, got {len(rows)}")
        elif rows[0][0] != 5.0 or abs(rows[-1][0] - 25.1) > 1.0e-9:
            error(f"real PDOS fixture {name}: energy window must be 5.0..25.1, "
                  f"got {rows[0][0]}..{rows[-1][0]}")

    # thermo_pw elastic constants (thermo_pw example13, Si): the constants
    # file is 24 numeric rows in the alternating 4+2 grammar (two 6x6 blocks:
    # stiffness then compliance) and the run stdout carries the 'i j='-headed
    # C_ij block plus the Voigt/Reuss/VRH schemes and sound/Debye prints.
    elcons = real("output_el_cons.dat.g1")
    if elcons:
        rows = [[float(x.replace("D", "E")) for x in REAL_FREQ_NUM.findall(l)]
                for l in elcons.splitlines() if l.strip()]
        if len(rows) != 24:
            error(f"real thermo_pw fixture: expected 24 numeric rows, got {len(rows)}")
        elif any(len(r) not in (4, 2) for r in rows):
            error("real thermo_pw fixture: rows must alternate 4+2 numbers")
        elif abs(rows[0][0] - 1588.860492) > 1.0e-6 or abs(rows[6][3] - 800.4009608) > 1.0e-6:
            error(f"real thermo_pw fixture: stiffness C11/C44 mismatch "
                  f"({rows[0][0]}, {rows[6][3]})")
    elout = real("thermopw_si_elastic.out")
    if elout:
        if "Elastic constants C_ij (kbar)" not in elout:
            error("real thermo_pw stdout fixture missing the C_ij block")
        if "Voigt-Reuss-Hill average of the two approximations:" not in elout:
            error("real thermo_pw stdout fixture missing the VRH scheme")
        if "8751.406 m/s" not in elout:
            error("real thermo_pw stdout fixture missing the sound velocities")

    # The total-DOS file: header '# E (eV) dosup(E) dosdw(E) pdosup(E)
    # pdosdw(E)'. The dos columns (1 and 2) are the total DOS; the bare 'E'
    # inside 'dosup(E)' must NOT hijack the energy column (that bug is why
    # total files were never parsed).
    tot = real("ni.pdos_tot")
    if tot:
        header = next((l for l in tot.splitlines() if l.strip().startswith("#")), "")
        if "dosup" not in header or "dosdw" not in header:
            error(f"real PDOS fixture ni.pdos_tot: unexpected header {header[:60]}")
        rows = []
        for line in tot.splitlines():
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            toks = [float(x.replace("D", "E")) for x in REAL_FREQ_NUM.findall(t)]
            if len(toks) >= 5:
                rows.append(toks)
        if len(rows) != 202:
            error(f"real PDOS fixture ni.pdos_tot: expected 202 rows, got {len(rows)}")
        elif rows[0][0] != 5.0 or abs(rows[-1][0] - 25.1) > 1.0e-9:
            error(f"real PDOS fixture ni.pdos_tot: energy window must be 5.0..25.1")
        elif abs((rows[0][1] + rows[0][2]) - -6.07e-06) > 1.0e-12:
            error(f"real PDOS fixture ni.pdos_tot: first dos sum "
                  f"{rows[0][1] + rows[0][2]} != -6.07e-06")
        elif abs((rows[-1][1] + rows[-1][2]) - 0.221) > 1.0e-9:
            error(f"real PDOS fixture ni.pdos_tot: last dos sum "
                  f"{rows[-1][1] + rows[-1][2]} != 0.221")

    # UPF v1 PP_HEADER field order, per upflib/read_upf_v1.f90: element on the
    # 2nd non-empty line, type 3rd, ..., mesh 10th, nwfc/nprj 11th.
    upf_cases = {
        "Rh.pbe-rrkjus_lb.UPF": ("Rh", "US", "9.00000000000", "1491", "2", "3"),
        "Rhs.pbe-rrkjus_lb.UPF": ("Rh", "US", "10.00000000000", "1491", "2", "3"),
        "C.UPF": ("C", "NC", "4.00000000000", "461", "3", "2"),
        "C_3.98148.UPF": ("C", "NC", "3.98148000000", "461", "3", "2"),
    }
    for name, (element, ptype, zval, mesh, nwfc, nprj) in upf_cases.items():
        text = real(name)
        if not text:
            continue
        m = re.search(r"<PP_HEADER>(.*?)</PP_HEADER>", text, re.S)
        if not m:
            error(f"real UPF fixture {name} has no PP_HEADER")
            continue
        lines = [l for l in m.group(1).splitlines() if l.strip()]
        if len(lines) < 11:
            error(f"real UPF fixture {name}: PP_HEADER has {len(lines)} lines, "
                  f"expected 11")
            continue
        fields = (lines[1].split()[0], lines[2].split()[0], lines[5].split()[0],
                  lines[9].split()[0], lines[10].split()[0], lines[10].split()[1])
        if fields != (element, ptype, zval, mesh, nwfc, nprj):
            error(f"real UPF fixture {name}: header fields {fields} != "
                  f"{(element, ptype, zval, mesh, nwfc, nprj)}")


def main() -> int:
    si = read("scf_si_converged.log")
    rows = scf_iterations(si)
    if len(rows) < 4:
        error(f"si fixture expected >=4 energy lines, got {len(rows)}")
    if not any(converged for _, converged in rows):
        error("si fixture missing ! converged total energy")
    if NOT_CONV.search(si):
        error("si fixture unexpectedly not-converged")
    if OCC_PAIR.findall(si) or OCC_SINGLE.findall(si):
        error("si fixture unexpectedly carries occupation needles")

    bad = read("scf_not_converged.log")
    if not NOT_CONV.search(bad):
        error("non-converged fixture missing marker")
    if not scf_iterations(bad):
        error("non-converged fixture has no energy lines")

    fe = read("scf_fe_spin.log")
    if "nspin" not in fe.lower() and "magnetization" not in fe.lower():
        error("fe spin fixture missing spin/magnetization markers")
    if not any(c for _, c in scf_iterations(fe)):
        error("fe spin fixture missing converged energy")
    if OCC_PAIR.findall(fe) or OCC_SINGLE.findall(fe):
        error("fe metal fixture unexpectedly carries occupation needles")

    # #47 acceptance-class matrix (batch 148): spin-polarized insulator with
    # FIXED occupations prints one PAIR line per SCF step (all kept - no
    # last-wins); an alkali-like partial-occupation metal with SMEARING
    # prints SINGLE lines, and its gap must stay UNDEFINED.
    paired = read("scf_spin_paired.log")
    pair_hits = OCC_PAIR.findall(paired)
    if len(pair_hits) != 4:
        error(f"spin-paired fixture expected 4 pair lines, got {len(pair_hits)}")
    if OCC_SINGLE.findall(paired):
        error("spin-paired fixture unexpectedly carries single lines")
    if "nspin" not in paired.lower():
        error("spin-paired fixture missing nspin marker")
    if paired.lower().count("total magnetization") < 5:
        error("spin-paired fixture expected per-step magnetization lines")
    if "fermi energy" in paired.lower():
        error("spin-paired insulator fixture must NOT print a Fermi energy")
    if not any(c for _, c in scf_iterations(paired)):
        error("spin-paired fixture missing converged energy")
    if NOT_CONV.search(paired):
        error("spin-paired fixture unexpectedly not-converged")

    partial = read("scf_partial_occupation.log")
    single_hits = OCC_SINGLE.findall(partial)
    if len(single_hits) != 2:
        error(f"partial-occupation fixture expected 2 single lines, "
              f"got {len(single_hits)}")
    if OCC_PAIR.findall(partial):
        error("partial-occupation fixture unexpectedly carries pair lines")
    if "fermi energy" not in partial.lower():
        error("partial-occupation fixture missing Fermi-energy line")
    if "smearing" not in partial.lower():
        error("partial-occupation fixture missing smearing marker")
    if "magnetization" in partial.lower():
        error("partial-occupation fixture must NOT claim magnetization")
    if not any(c for _, c in scf_iterations(partial)):
        error("partial-occupation fixture missing converged energy")
    if NOT_CONV.search(partial):
        error("partial-occupation fixture unexpectedly not-converged")

    relax = read("relax_converged.log")
    if not BFGS.search(relax):
        error("relax fixture missing BFGS/end marker")

    if not MISSING_PSEUDO.search(read("error_missing_pseudo.log")):
        error("missing-pseudo fixture not matched")

    bands = read("bands_path.log")
    if len(HIGH_SYM.findall(bands)) < 3:
        error("bands fixture needs >=3 high-symmetry points")

    dos = read("dos_header.log")
    if "E (eV)" not in dos or "EFermi" not in dos:
        error("dos fixture missing header markers")

    # Source presence checks for batch-4 modules
    for rel in [
        "src/quantumforge/run/QECommandDag.java",
        "src/quantumforge/run/QECommandStage.java",
        "src/quantumforge/run/RestartManager.java",
        "src/quantumforge/run/WorkflowExporter.java",
        "src/quantumforge/run/ArtifactScanner.java",
        "src/quantumforge/run/DryRunPreflight.java",
        "src/quantumforge/tools/XCrySDenLauncher.java",
        "src/quantumforge/app/project/viewer/recovery/RecoveryAction.java",
        "src/quantumforge/ssh/KnownHostsStore.java",
        "src/quantumforge/ssh/JschSshTransport.java",
        "src/quantumforge/hpc/SlurmSchedulerAdapter.java",
        "src/quantumforge/symmetry/SpglibService.java",
        "src/quantumforge/app/ssh/HostKeyAcceptance.java",
        "src/quantumforge/ssh/SyncChecksumCache.java",
        "tests/fixtures/qe/data-file-schema.xml",
        "src/quantumforge/hpc/RemoteJobMonitor.java",
        "src/quantumforge/com/secrets/WindowsCredentialBackend.java",
        "src/quantumforge/run/parser/PhononDosThermodynamics.java",
        "src/quantumforge/run/CheckpointResubmit.java",
        "src/quantumforge/builder/neb/NEBPathCreator.java",
        "src/quantumforge/run/parser/QeXmlResultParser.java",
        "src/quantumforge/com/secrets/ProcessKeyringBackend.java",
        "src/quantumforge/hpc/JobQueueStore.java",
        "src/quantumforge/hpc/SgeSchedulerAdapter.java",
        "src/quantumforge/ssh/SelectiveResultSync.java",
        "src/quantumforge/hpc/PbsSchedulerAdapter.java",
        "tools/spglib_sidecar.py",
    ]:
        if not (ROOT / rel).is_file():
            error(f"missing source {rel}")


# --- Real captured thermo_pw outputs (tests/fixtures/thermo_pw/real) ---------
# Byte-for-byte copies of the upstream thermo_pw examples' reference outputs
# (dalcorso/thermo_pw, commit de904e936073359a82d6c5994d0c40deaaffe689; see
# real/PROVENANCE.md). The invariants mirror the Java parser tests so a
# damaged copy is caught offline too.

TPW = ROOT / "tests" / "fixtures" / "thermo_pw" / "real"


def check_thermo_pw_real_fixtures() -> None:
    if not (TPW / "PROVENANCE.md").is_file():
        error("thermo_pw real fixture directory must ship PROVENANCE.md")
        return

    def tpw(name: str) -> str:
        path = TPW / name
        if not path.is_file():
            error(f"missing thermo_pw real fixture {name}")
            return ""
        return path.read_text(encoding="utf-8")

    # output_ev.dat (Al, mur_lc): 2-column volume/energy pairs.
    ev = tpw("output_ev_al.dat")
    if ev:
        rows = [l.split() for l in ev.splitlines() if l.strip()]
        if len(rows) < 4 or any(len(r) != 2 for r in rows):
            error("output_ev_al.dat must hold 2-column volume/energy rows")

    # output_anhar.dat (Si, mur_lc_t): '#' header then 4-column T/V/F/beta.
    anhar = tpw("output_anhar_si.dat")
    if anhar:
        head = [l for l in anhar.splitlines() if l.startswith("#")]
        if not any("beta is the volume thermal expansion" in l for l in head):
            error("output_anhar_si.dat lost its '# beta is the volume thermal expansion' header")

    # output_eltherm.dat (Al, scf_dos): '#' header then 6-column rows.
    eltherm = tpw("output_eltherm_al.dat")
    if eltherm:
        head = [l for l in eltherm.splitlines() if l.startswith("#")]
        if not any("Chemical potential in Ry" in l for l in head):
            error("output_eltherm_al.dat lost its '# Chemical potential in Ry' header")

    # output_grun.dat (Si, mur_lc_t): the &plot band-style row matrix.
    grun = tpw("output_grun_si.dat")
    if grun and "&plot" not in grun.splitlines()[0]:
        error("output_grun_si.dat must start with the '&plot nbnd=.., nks=..' header")

    # output_el_cons_si.g1: the 12-line 4+2-float stiffness block.
    elcons = tpw("output_el_cons_si.g1")
    if elcons:
        nums = [float(x) for x in elcons.split()]
        if len(nums) < 72 or abs(nums[0] - 1588.860492) > 1e-3:
            error("output_el_cons_si.g1 must start with the Si C11 1588.86 kbar block")

    # keconv/nkconv: '#' header + numeric rows.
    for name, needle in [("output_keconv_cu.dat", "E_kin (Ry)"),
                         ("output_nkconv_cu.dat", "nk1")]:
        text = tpw(name)
        if text and not any(needle in l for l in text.splitlines() if l.startswith("#")):
            error(f"{name} lost its '# ... {needle} ...' header")


    check_thermo_pw_real_fixtures()
    check_real_fixtures()
    check_golden_fixtures()

    if ERRORS:
        print("Fixture harness FAILED:")
        for e in ERRORS:
            print(" -", e)
        return 1
    xml = FIX / "data-file-schema.xml"
    if not xml.is_file():
        error("missing data-file-schema.xml fixture")
    else:
        text = xml.read_text(encoding="utf-8")
        if "fermi_energy" not in text or "etot" not in text:
            error("QE XML fixture missing fermi/etot fields")

    print("Fixture harness passed:", len(list(FIX.glob('*.log'))), "log fixtures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
