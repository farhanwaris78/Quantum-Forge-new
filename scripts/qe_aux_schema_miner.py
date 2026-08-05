#!/usr/bin/env python3
"""Mine the QE AUXILIARY-program input grammars (24 programs) into generated
Java, per release tag qe-7.2 .. qe-7.6.

Ground truth (QE is GPL - only metadata FACTS are extracted; no doc prose):

  * 21 programs ship QE's OWN machine grammar INPUT_*.def files (the files the
    INPUT_*.html documentation is generated FROM): namelist membership,
    declared types, declared defaults, REQUIRED flags (status{}), documented
    option literals ('opt -val' records) - mined with the SAME parser the
    pw/ph/hp miner uses (imported, never re-implemented here);
  * the 3 XSpectra-family programs have NO .def grammar: their namelist
    declarations are mined from the compilable source instead
    (XSpectra/src/read_input_and_bcast.f90: INPUT_XSPECTRA/PLOT/PSEUDOS/
    CUT_OCC; XSpectra/src/spectra_correction.f90: INPUT_MANIP - shared by
    spectra_correction.x AND spectra_manipulation.x, the INPUT_SPECTRA_*
    docs say so themselves);
  * spectra_correction.f90's option guard (STOP 'Option not recognized') is a
    HARD abort-set mined verbatim ('cut_occ_states', 'add_L2_L3',
    'convolution') - a STOP, not an errore, and the fact line says exactly
    that.

Per-keyword/per-literal presence across the five tags becomes the same 5-bit
mask scheme as the namelist schema (bit i = VERSIONS[i]); keywords the file
of a tag does not declare stay ABSENT for that tag (never invented).

Inputs: a directory prepared as
  git show qe-<tag>:<relpath> > <dir>/<relpath with '/'->'_'>._<tag>
(see the batch-159 extraction command in docs/ROADMAP.md).

Usage: python3 scripts/qe_aux_schema_miner.py /dir/with/aux/files
"""
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qe_schema_miner import (  # noqa: E402  (single implementation of .def truth)
    VERSIONS, parse_def, parse_namelist_source,
)

# ---------------------------------------------------------------- programs
# label -> (DEF path) or (SRC path, routed namelists). Doc page for the audit
# footer links (the user's mandate URLs, exactly as published by QE).
DEF_PROGRAMS = {
    "bgw2pw": "PP/Doc/INPUT_bgw2pw.def",
    "pw2bgw": "PP/Doc/INPUT_pw2bgw.def",
    "pwcond": "PWCOND/Doc/INPUT_PWCOND.def",
    "pprism": "PP/Doc/INPUT_PPRISM.def",
    "oscdft_et": "PP/Doc/INPUT_OSCDFT_ET.def",
    "oscdft": "PW/Doc/INPUT_OSCDFT.def",
    "dynmat": "PHonon/Doc/INPUT_DYNMAT.def",
    "matdyn": "PHonon/Doc/INPUT_MATDYN.def",
    "postahc": "PHonon/Doc/INPUT_POSTAHC.def",
    "q2r": "PHonon/Doc/INPUT_Q2R.def",
    "d3hess": "PP/Doc/INPUT_D3HESS.def",
    "neb": "NEB/Doc/INPUT_NEB.def",
    "cp": "CPV/Doc/INPUT_CP.def",
    "cppp": "CPV/Doc/INPUT_CPPP.def",
    "lanczos": "TDDFPT/Doc/INPUT_Lanczos.def",
    "spectrum": "TDDFPT/Doc/INPUT_Spectrum.def",
    "davidson": "TDDFPT/Doc/INPUT_Davidson.def",
    "magnon": "TDDFPT/Doc/INPUT_Magnon.def",
    "eels": "TDDFPT/Doc/INPUT_EELS.def",
    "ld1": "atomic/Doc/INPUT_LD1.def",
    "all_currents": "QEHeat/Doc/INPUT_ALL_CURRENTS.def",
}
SRC_PROGRAMS = {
    "xspectra": ("XSpectra/src/read_input_and_bcast.f90",
                 ["INPUT_XSPECTRA", "PLOT", "PSEUDOS", "CUT_OCC"]),
    "spectra_correction": ("XSpectra/src/spectra_correction.f90",
                           ["INPUT_MANIP"]),
    "spectra_manipulation": ("XSpectra/src/spectra_correction.f90",
                             ["INPUT_MANIP"]),
}
DOC_PAGES = {
    "bgw2pw": "INPUT_bgw2pw.html", "pw2bgw": "INPUT_pw2bgw.html",
    "pwcond": "INPUT_PWCOND.html", "pprism": "INPUT_PPRISM.html",
    "oscdft_et": "INPUT_OSCDFT_ET.html", "oscdft": "INPUT_OSCDFT.html",
    "dynmat": "INPUT_DYNMAT.html", "matdyn": "INPUT_MATDYN.html",
    "postahc": "INPUT_POSTAHC.html", "q2r": "INPUT_Q2R.html",
    "d3hess": "INPUT_D3HESS.html", "neb": "INPUT_NEB.html",
    "cp": "INPUT_CP.html", "cppp": "INPUT_CPPP.html",
    "lanczos": "INPUT_Lanczos.html", "spectrum": "INPUT_Spectrum.html",
    "davidson": "INPUT_Davidson.html", "magnon": "INPUT_Magnon.html",
    "eels": "INPUT_EELS.html", "xspectra": "INPUT_XSPECTRA",
    "spectra_correction": "INPUT_SPECTRA_CORRECTION",
    "spectra_manipulation": "INPUT_SPECTRA_MANIPULATION",
    "ld1": "INPUT_LD1.html", "all_currents": "INPUT_ALL_CURRENTS.html",
}
# Emission order = the mandated publication order of the 24 INPUT_* docs
# (grammar presence never depends on this order; it is the stable display and
# pin order for QEAuxSchema.programs()).
ALL_PROGRAM_LABELS = [
    "bgw2pw", "pw2bgw", "pwcond", "pprism", "oscdft_et", "oscdft", "dynmat",
    "matdyn", "postahc", "q2r", "d3hess", "neb", "cp", "cppp", "lanczos",
    "spectrum", "davidson", "magnon", "eels", "xspectra", "spectra_correction",
    "spectra_manipulation", "ld1", "all_currents",
]
assert (set(ALL_PROGRAM_LABELS) == set(DEF_PROGRAMS) | set(SRC_PROGRAMS)
        and len(ALL_PROGRAM_LABELS) == 24)


def local_name(relpath: str, version: str) -> str:
    return relpath.replace("/", "_") + "._" + version


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def java_text(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def mask_of(present) -> int:
    mask = 0
    for i, version in enumerate(VERSIONS):
        if version in present:
            mask |= 1 << i
    return mask


def mine_option_stopset(source: str):
    """spectra_correction.f90's option guard -> (literals, verbatim stop msg)."""
    guard = re.search(
        r"IF\s*\(\s*TRIM\(ADJUSTL\(option\)\)\s*\.ne\..*?\)\s*then(.*?)(?:ENDIF|endif)",
        source, re.DOTALL)
    if not guard:
        return [], ""
    literals = re.findall(r"\.ne\.\s*'([^']+)'", guard.group(0))
    body = guard.group(1)
    stopped = "stop" in body.lower()
    msgs = re.findall(r"write\s*\(\s*6\s*,\s*\*\s*\)\s*'([^']*)'", body)
    note = "; ".join(msgs) + (" -> stop" if stopped else "")
    return literals, note


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    indir = Path(sys.argv[1])

    # ------------------------------------------------ per-(program,version) mining
    # program -> version -> {key: KeywordEntry-shaped tuple}
    mined = {}
    namelists_seen = {}
    fingerprints = {}
    hard_facts = {}  # program -> [(text, version)]
    for program in ALL_PROGRAM_LABELS:
        mined[program] = {}
        namelists_seen[program] = {}
        hard_facts[program] = []
        is_def = program in DEF_PROGRAMS
        relpath = DEF_PROGRAMS.get(program) or SRC_PROGRAMS[program][0]
        for version in VERSIONS:
            path = indir / local_name(relpath, version)
            if not path.is_file():
                raise SystemExit(f"missing ground truth: {path}")
            text = path.read_text(encoding="utf-8", errors="replace")
            fingerprints[(program, version)] = sha256(path)
            if is_def:
                entries = {}
                stats = parse_def(text, program, entries)
                mined[program][version] = entries
                namelists_seen[program][version] = stats["namelists"]
            else:
                decls = parse_namelist_source(text)  # {namelist: {var: (type,dims)}}
                routed = set(SRC_PROGRAMS[program][1])
                entries = {}
                for namelist, members in decls.items():
                    if namelist not in routed:
                        continue
                    for var, (type_name, dims) in members.items():
                        entries[var.lower()] = {
                            "name": var,
                            "type": type_name or "UNKNOWN",
                            "dims": dims, "default": None,
                            "required": False, "options": [],
                            "src_namelist": namelist,
                        }
                mined[program][version] = entries
                namelists_seen[program][version] = sorted(routed)
                if program == "spectra_correction":
                    literals, note = mine_option_stopset(text)
                    if literals:
                        hard_facts[program].append(
                            ("option STOP-set: " + ", ".join(literals)
                             + " (guard: " + note + ")", version))

    # ------------------------------------------------ masks + assembly
    def kw_key(row):
        return row.name if hasattr(row, "name") else row["name"]

    out = []
    out.append("/* GENERATED by scripts/qe_aux_schema_miner.py - do not hand-edit.")
    out.append(" * Mined per tag qe-7.2 .. qe-7.6 from github.com/QEF/q-e:")
    out.append(" * 21 INPUT_*.def machine grammars + the XSpectra-family namelist")
    out.append(" * declarations from compilable source (INPUT_XSPECTRA/PLOT/PSEUDOS/CUT_OCC")
    out.append(" * from read_input_and_bcast.f90; INPUT_MANIP from spectra_correction.f90,")
    out.append(" * shared by spectra_correction.x and spectra_manipulation.x per their own")
    out.append(" * docs). Presence masks are 5-bit, bit i = "
               + ", ".join(VERSIONS) + " (i ascending).")
    out.append(" * Provenance: grammmar facts only - declared types/defaults/REQUIRED from")
    out.append(" * .def records, documented option literals as SOFT hints (no doc prose),")
    out.append(" * source-declared types for the def-less programs; unknown keywords abort")
    out.append(" * at the Fortran namelist READ in every one of these programs (language-")
    out.append(" * level fact, mirrored as ERROR); HARD sets only where mined verbatim")
    out.append(" * (spectra_correction option STOP-set). Tag sha256 fingerprints below. */")
    out.append("package quantumforge.input.schema;")
    out.append("")
    out.append("import java.util.ArrayList;")
    out.append("import java.util.List;")
    out.append("")
    out.append("/** Generated mined auxiliary-program grammar table (24 programs). */")
    out.append("final class QEAuxSchemaData {")
    out.append("")
    for program in ALL_PROGRAM_LABELS:
        out.append(f"/* {program}: " + "; ".join(
            f"{v}=sha256:{fingerprints[(program, v)][:16]}" for v in VERSIONS) + " */")
    out.append("")
    out.append("    static List<QEAuxSchema.Row> buildRows() {")
    out.append("        List<QEAuxSchema.Row> rows = new ArrayList<>();")
    total = 0
    for program in ALL_PROGRAM_LABELS:
        is_def = program in DEF_PROGRAMS
        union_keys = []
        for version in VERSIONS:
            for key in mined[program][version]:
                if key not in union_keys:
                    union_keys.append(key)
        # namelist membership + order from the newest tag carrying the keyword
        for key in union_keys:
            present = [v for v in VERSIONS if key in mined[program][v]]
            newest_v = present[-1]
            if is_def:
                record = mined[program][newest_v][key]
                namelist = record.namelist
                type_name = record.type_name or "UNKNOWN"
                default = record.default_by_version.get("_def")
                required = record.required
                options = record.doc_options
            else:
                record = mined[program][newest_v][key]
                namelist = record["src_namelist"]
                type_name = record["type"]
                default = None
                required = False
                options = []
            mask = mask_of(present)
            total += 1
            # per-literal presence across tags (def programs; src has none)
            lit_masks = {}
            if is_def:
                for version in VERSIONS:
                    record_v = mined[program][version].get(key)
                    if record_v is not None:
                        for literal in (record_v.doc_options or []):
                            lit_masks.setdefault(literal, set()).add(version)
            opt_lit = list(lit_masks) if lit_masks else list(options)
            def lit_mask(o):
                return mask_of(lit_masks[o]) if o in lit_masks else mask
            opt_csv = ",".join(f"{o}~0x{lit_mask(o):02X}" for o in opt_lit)
            default_repr = "null" if default is None else java_text(default)
            out.append(f'        rows.add(QEAuxSchema.row("{program}", "{namelist}",'
                       f' "{kw_key(record)}", "{type_name}", {default_repr},'
                       f' {str(required).lower()}, 0x{mask:02X}, "{opt_csv}"));')
    out.append("        return rows;")
    out.append("    }")
    out.append("")
    out.append("    /** Program label -> QE doc page of record (the published INPUT_* page). */")
    out.append("    static List<String> buildDocPages() {")
    doc_items = ", ".join(f'"{p}~{DOC_PAGES[p]}"' for p in ALL_PROGRAM_LABELS)
    out.append(f"        return List.of({doc_items});")
    out.append("    }")
    out.append("")
    out.append("    /** Verbatim HARD facts with presence masks (bounded, mined). */")
    out.append("    static List<String> buildFacts() {")
    fact_rows = []
    for program, rows in hard_facts.items():
        if not rows:
            continue
        texts = []
        for text, version in rows:
            if text not in texts:
                texts.append(text)
        for text in texts:
            mask = mask_of([v for _t, v in rows if _t == text])
            fact_rows.append((program, text, mask))
    out.append("        return List.of(")
    for index, (program, text, mask) in enumerate(fact_rows[:16]):
        comma = "," if index < len(fact_rows[:16]) - 1 else ""
        out.append(f'            {java_text(program + ": " + text)} + "~0x{mask:02X}"{comma}')
    out.append("        );")
    out.append("    }")
    out.append("}")
    target = Path("src/quantumforge/input/schema/QEAuxSchemaData.java")
    target.write_text("\n".join(out) + "\n", encoding="utf-8", newline="")
    print(f"rows emitted: {total} across {len(ALL_PROGRAM_LABELS)} programs -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
