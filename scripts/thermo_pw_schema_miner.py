#!/usr/bin/env python3
"""Mine the thermo_pw &INPUT_THERMO grammar into generated Java.

Ground truth (mined verbatim, never paraphrased), per release tag:
  * thermo_readin_<tag>.f90
      - the NAMELIST / input_thermo / declaration: the keyword set plus the
        code's OWN group-header comments ("!  mur_lc", "!  scf_disp", ...)
        carried as raw grouping labels (bookkeeping comments, not a spec);
      - the procedural default assignments between the anchors
        "Default values of the input variables" and "IF (meta_ionode) READ(";
      - the post-READ consistency `CALL errore('thermo_readin', ...)` lines,
        kept verbatim as fact lines;
      - the READ(iun_thermo, input_thermo ...) -> errore(...) line proving an
        unknown keyword is FATAL (HARD).
  * initialize_<tag>.f90
      - the part-1 SELECT CASE (TRIM(what)) arms with the CASE DEFAULT
        errore (HARD accepted set for `what`).

Version window (R6 slice 2): thermo_pw's OWN release tags
2.0.0, 2.0.1, 2.0.2, 2.0.3, 2.1.0, 2.1.1 plus the fingerprinted development
master commit (newest column) - the window is thermo_pw-tag-indexed, never
QE-paired (no README/source statement pairs the two version lines). Each
keyword, what value and consistency fact carries a 7-bit presence mask;
defaults/types keep the NEWEST reading with per-tag drift recorded verbatim
(e.g. old_ec: '.TRUE.' (LOGICAL) at 2.0.0, 0 (INTEGER) since 2.0.1).

Output: src/quantumforge/input/schema/QEThermoPwSchemaData.java (generated).

Usage: python3 scripts/thermo_pw_schema_miner.py /dir/with/by-tag-files
(the directory must contain thermo_readin_<tag>.f90, initialize_<tag>.f90
and commit.txt as produced by the batch-158 extraction commands).
"""
import hashlib
import re
import sys
from pathlib import Path

VERSIONS = ["2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.1.0", "2.1.1", "master"]
NAMELIST_END = re.compile(r"^\s*IF \(meta_ionode\) READ", re.MULTILINE)
DEFAULTS_ANCHOR = "Default values of the input variables"


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_namelist(readin: str):
    """(ordered unique keywords with group labels), (duplicate names)."""
    start = readin.index("NAMELIST / input_thermo /")
    block_end = readin.index("parse_unit_save", start)
    block = readin[start:block_end]
    group = "declared before any group header"
    lines = block.splitlines()
    lines[0] = lines[0].split("NAMELIST / input_thermo /", 1)[1]
    entries = []  # (name, [groups...])
    for raw in lines:
        comment = re.match(r"^\s*!\s*(.+?)\s*$", raw)
        if comment:
            text = comment.group(1)
            if text:
                group = text
            continue
        code = raw.split("!")[0]
        for name in re.findall(r"[A-Za-z][A-Za-z0-9_]*", code):
            if name in ("NAMELIST",):
                continue
            if not entries or entries[-1][0] != name:
                for existing, groups in entries:
                    if existing == name:
                        if group not in groups:
                            groups.append(group)
                        break
                else:
                    entries.append((name, [group]))
    seen = set()
    unique = []
    duplicates = set()
    for name, _groups in entries:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    for name, groups in entries:
        if not any(n == name for n, _ in unique):
            unique.append((name, groups))
    return unique, duplicates


def parse_defaults(readin: str):
    start = readin.index(DEFAULTS_ANCHOR)
    end = re.search(NAMELIST_END, readin[start:]).start() + start
    section = readin[start:end]
    defaults = {}
    order = 0
    for raw in section.splitlines():
        code = raw.split("!")[0].strip()
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*(?:\([^)]*\))?)\s*=\s*(.+?)\s*$", code)
        if not m:
            continue
        name, rhs = m.group(1), m.group(2).rstrip(",")
        # element-wise array assignments are recorded as their base name:
        # the miner does not invent a dimension grammar, the RHS text stays.
        base = name.split("(")[0]
        order += 1
        defaults[base] = (rhs, order)  # last assignment wins (execution order)
    return defaults


def infer_type(rhs: str) -> str:
    rhs = rhs.strip()
    if re.fullmatch(r"\.TRUE\.|\.FALSE\.", rhs.upper()):
        return "LOGICAL"
    if rhs.startswith("'") and rhs.endswith("'"):
        return "CHARACTER"
    if re.fullmatch(r"[+-]?\d+", rhs):
        return "INTEGER"
    core = re.sub(r"_(DP|dp|QP|qp|SP|sp)$", "", rhs)  # kind suffix is part of the literal
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)([eEdD][+-]?\d+)?", core) \
            or re.fullmatch(r"[+-]?\d+[eEdD][+-]?\d+", core):
        return "REAL"
    return "UNKNOWN"


def parse_what_values(initwork: str) -> list:
    start = initwork.index("SELECT CASE (TRIM(what))")
    end = initwork.index("END SELECT", start)
    block = initwork[start:end]
    if "what not recognized" not in block:
        raise SystemExit("hard-set proof missing: CASE DEFAULT errore not found")
    values = []
    for case in re.findall(r"CASE\s*\(([^)]*)\)", block):
        for literal in re.findall(r"'([^']*)'", case):
            if literal.strip() and literal not in values:
                values.append(literal)
    return values


def parse_consistency_facts(readin: str) -> list:
    start = re.search(NAMELIST_END, readin).start()
    lines = readin[start:].splitlines()
    facts = []
    i = 0
    while i < len(lines) and len(facts) < 24:
        line = lines[i]
        if "END SUBROUTINE thermo_readin" in line:
            break
        if "errore('thermo_readin'" in line:
            stmt = line.strip()
            extra = 0
            # Fortran continuation: trailing '&' on this line, optional leading
            # '&' on the next - join to one statement.
            while stmt.rstrip().endswith("&") and i + extra + 1 < len(lines):
                stmt = stmt.rstrip()[:-1].rstrip()
                nxt = lines[i + extra + 1].strip()
                if nxt.startswith("&"):
                    nxt = nxt[1:].lstrip()
                stmt = stmt + " " + nxt
                extra += 1
            stmt = " ".join(stmt.split())
            if stmt.count("(") == stmt.count(")") and "(" in stmt:
                facts.append(stmt)
            i += extra
        i += 1
    return facts


def java_text(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    indir = Path(sys.argv[1])
    commit = (indir / "commit.txt").read_text(encoding="utf-8").strip()

    per_version = {}
    fingerprints = {}
    for version in VERSIONS:
        readin_path = indir / f"thermo_readin_{version}.f90"
        initwork_path = indir / f"initialize_{version}.f90"
        for path in (readin_path, initwork_path):
            if not path.is_file():
                raise SystemExit(f"missing ground truth: {path}")
        readin = readin_path.read_text(encoding="utf-8", errors="replace")
        initwork = initwork_path.read_text(encoding="utf-8", errors="replace")
        entries, _dups = parse_namelist(readin)
        per_version[version] = {
            "entries": entries,
            "defaults": parse_defaults(readin),
            "what": parse_what_values(initwork),
            "facts": parse_consistency_facts(readin),
        }
        fingerprints[version] = (sha256_bytes(readin_path),
                                 sha256_bytes(initwork_path))

    newest = VERSIONS[-1]

    def mask_of(present_versions) -> int:
        mask = 0
        for i, version in enumerate(VERSIONS):
            if version in present_versions:
                mask |= 1 << i
        return mask

    # Keyword union in newest-first order (the newest table order is the
    # canonical declaration order; keywords absent there append afterwards).
    newest_names = [name for name, _ in per_version[newest]["entries"]]
    union_names = list(newest_names)
    for version in VERSIONS:
        for name, _groups in per_version[version]["entries"]:
            if name not in union_names:
                union_names.append(name)

    out = []
    out.append("/* GENERATED by scripts/thermo_pw_schema_miner.py - do not hand-edit.")
    out.append(" * Mined from the thermo_pw project (github.com/dalcorso/thermo_pw) at")
    out.append(" * window " + ", ".join(VERSIONS[:-1])
               + f" + master commit {commit},")
    for version in VERSIONS:
        fpr = fingerprints[version]
        out.append(f" * {version}: thermo_readin sha256={fpr[0]},")
        out.append(f" * {' ' * len(version)}  initialize_thermo_work sha256={fpr[1]},")
    out.append(" * extracted 2026-07-21 from release tags + the pinned master commit.")
    out.append(" * Provenance rules: keyword set + group labels + procedural defaults come")
    out.append(" * from the NAMELIST declaration and the defaults section of thermo_readin.f90;")
    out.append(" * the HARD accepted values of `what` come from the part-1 SELECT CASE")
    out.append(" * (TRIM(what)) whose CASE DEFAULT calls errore('what not recognized'); the")
    out.append(" * read path (READ(iun_thermo, input_thermo...) -> errore) makes an unknown")
    out.append(" * keyword FATAL, mirrored as ERROR severity. Presence masks are 7-bit, bit i")
    out.append(" * = window index i (newest = master). Types/defaults are the NEWEST reading;")
    out.append(" * per-tag deviations ride in the drift column verbatim (INFERRED types). */")
    out.append("package quantumforge.input.schema;")
    out.append("")
    out.append("import java.util.ArrayList;")
    out.append("import java.util.List;")
    out.append("")
    out.append("/** Generated mined thermo_pw &INPUT_THERMO grammar table (version window). */")
    out.append("final class QEThermoPwSchemaData {")
    out.append("")
    out.append("    static List<QEThermoPwSchema.Entry> buildEntries() {")
    out.append("        List<QEThermoPwSchema.Entry> entries = new ArrayList<>();")
    newest_groups = {name: groups for name, groups in per_version[newest]["entries"]}
    for name in union_names:
        present = [v for v in VERSIONS
                   if name in {n for n, _ in per_version[v]["entries"]}]
        groups = newest_groups.get(name)
        if groups is None:
            # keyword removed before master: groups from its freshest tag
            groups = next(g for n, g in
                          per_version[present[-1]]["entries"] if n == name)
        mask = mask_of(present)
        # newest reading of type/default + per-tag drift
        newest_default = per_version[newest]["defaults"].get(name)
        newest_text = None if newest_default is None else newest_default[0]
        newest_type = "UNKNOWN" if newest_text is None else infer_type(newest_text)
        drift_items = []
        for version in present[:-1]:
            tag_default = per_version[version]["defaults"].get(name)
            tag_text = None if tag_default is None else tag_default[0]
            tag_type = "UNKNOWN" if tag_text is None else infer_type(tag_text)
            if tag_text != newest_text or tag_type != newest_type:
                rendered = "<none>" if tag_text is None else tag_text
                drift_items.append(f"{version}:{tag_type}:{rendered}")
        drift_csv = ",".join(drift_items)
        default_repr = "null" if newest_text is None else java_text(newest_text)
        group_csv = ",".join(groups)
        out.append(f'        entries.add(QEThermoPwSchema.entry("{name}",'
                   f' QEThermoPwSchema.Type.{newest_type}, {default_repr},'
                   f' "{group_csv}", 0x{mask:02X}, {java_text(drift_csv)}));')
    out.append("        return entries;")
    out.append("    }")
    out.append("")
    out.append("    /** HARD accepted literals of `what` with presence masks"
               " (CASE DEFAULT -> errore). */")
    out.append("    static List<String> buildWhatAcceptedValues() {")
    what_union = []
    for version in VERSIONS:
        for value in per_version[version]["what"]:
            if value not in what_union:
                what_union.append(value)
    parts = ", ".join(
        f'"{value}~0x{mask_of([v for v in VERSIONS if value in per_version[v]["what"]]):02X}"'
        for value in what_union)
    out.append(f"        return List.of({parts});")
    out.append("    }")
    out.append("")
    out.append("    /** Verbatim consistency-check fact lines with presence masks. */")
    out.append("    static List<String> buildConsistencyFacts() {")
    fact_union = []
    for version in VERSIONS:
        for fact in per_version[version]["facts"]:
            if fact not in fact_union:
                fact_union.append(fact)
    out.append("        return List.of(")
    items = []
    for fact in fact_union[:32]:
        mask = mask_of([v for v in VERSIONS if fact in per_version[v]["facts"]])
        items.append((fact, mask))
    for index, (fact, mask) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        out.append(f'            {java_text(fact)} + "~0x{mask:02X}"{comma}')
    out.append("        );")
    out.append("    }")
    out.append("}")
    target = Path("src/quantumforge/input/schema/QEThermoPwSchemaData.java")
    target.write_text("\n".join(out) + "\n", encoding="utf-8", newline="")
    counts = {v: len(d["entries"]) for v, d in per_version.items()}
    print(f"mined union {len(union_names)} keywords (per-version {counts}),"
          f" {len(what_union)} what values, {len(fact_union)} fact lines -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
