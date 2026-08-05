#!/usr/bin/env python3
"""Machine-mines Quantum ESPRESSO namelist grammar into QuantumForge metadata.

Ground truth (never vendored into this repository - QE is GPL; only metadata
FACTS are extracted here): for each release tag qe-7.2 .. qe-7.6 the miner reads

  PW/Doc/INPUT_PW.def         namelist membership, declared types, declared
  PHonon/Doc/INPUT_PH.def     defaults, REQUIRED flags, documented option
  HP/Doc/INPUT_HP.def         literals ('opt -val' records). These .def files
                              are QE's own machine grammar from which the
                              INPUT_PW.html documentation is generated.
  Modules/input_parameters.f90    NAMELIST declarations + variable types from
  PHonon/PH/phq_readin.f90        the compilable source (catches keywords the
  HP/src/hp_readin.f90            docs grammar has not listed yet)
  PW/src/input.f90            the programs' OWN accepted-value switches:
  PHonon/PH/phq_readin.f90    Fortran SELECT CASE on CHARACTER is exact match,
                              so these arms are the literals pw.x/ph.x agree to
                              run with (mined per version - the accepted set
                              drifts, e.g. calculation='ensemble' is 7.6-only)

and emits src/quantumforge/input/schema/QESchemaData.java - a union table with
a per-keyword (and per accepted literal) presence mask over the five versions.
No documentation PROSE is copied into the generated file (licensing hygiene);
QENamelistSchema links QE's own online docs instead.

Usage:
  python3 scripts/qe_schema_miner.py --qe-src /tmp/qe_versions \
      --output src/quantumforge/input/schema/QESchemaData.java [--dump]
"""

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

VERSIONS = ["7.2", "7.3", "7.4", "7.5", "7.6"]
ALL_VERSION_MASK = (1 << len(VERSIONS)) - 1

PROGRAMS = {
    "pw": {
        "def_file": "INPUT_PW.def",
        "namelist_source": "input_parameters.f90",
        # set_occupations.f90 carries the occupations/smearing SELECT CASE
        # switches (invoked from PW/src/input.f90) - mined with the same rules.
        "case_files": ["pw_input.f90", "set_occupations.f90"],
    },
    "ph": {
        "def_file": "INPUT_PH.def",
        "namelist_source": "phq_readin.f90",
        "case_files": ["phq_readin.f90"],
    },
    "hp": {
        "def_file": "INPUT_HP.def",
        "namelist_source": "hp_readin.f90",
        "case_files": [],
    },
}

DOC_PAGES = {"pw": "INPUT_PW.html", "ph": "INPUT_PH.html", "hp": "INPUT_HP.html"}

ENTRY_HEAD = re.compile(
    r"(var|vargroup|dimension|multidimension|card|group|label)\b"
    r"(?:\s+([A-Za-z_][\w.%]*))?"
    r"(?:\s+-type\s+([A-Z]+))?"
    r"\s*\{")

VARGROUP_MEMBER = re.compile(
    r"^\s*var\s+([A-Za-z_][\w.]*)\s*"
    r"(?:-type\s+([A-Z]+))?\s*(?:\(([^)]*)\))?\s*(?:\{\s*\})?\s*$",
    re.MULTILINE)


@dataclass
class KeywordEntry:
    program: str
    name: str
    namelist: str
    type_name: str | None = None
    array_dims: str | None = None
    required: bool = False
    default_by_version: dict = field(default_factory=dict)
    doc_options: list = field(default_factory=list)
    hard_literal_masks: dict = field(default_factory=dict)  # accepted (errore-guarded)
    soft_literal_masks: dict = field(default_factory=dict)  # tolerated (remapped/pass-through)
    hard_enum: bool = False                                 # any mined switch refuses input
    mask: int = 0
    source_typed: bool = False  # type/namelist also confirmed by NAMELIST source


# ---------------------------------------------------------------- .def mining

def strip_records(text: str) -> str:
    """Drop the trailing-$ record markers of a .def file."""
    lines = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped.endswith("$"):
            stripped = stripped[:-1].rstrip()
        lines.append(stripped)
    return "\n".join(lines)


def match_brace(text: str, open_index: int) -> int:
    """Index just past the brace matching text[open_index] == '{'."""
    depth = 0
    for i in range(open_index, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced braces at index %d" % open_index)


def grab(text: str, key: str) -> str | None:
    """Extract 'key{ ... }' block contents (balanced) or None."""
    match = re.search(r"(?<![\w])" + re.escape(key)
                      + r"(?:\s+-kind\s+\w+)?\s*\{", text)
    if not match:
        return None
    open_index = text.index("{", match.start())
    close_index = match_brace(text, open_index)
    return text[open_index + 1: close_index - 1].strip()


def parse_doc_options(options_text: str) -> list:
    """Documented value literals from an options{} block.

    Two honest shapes only: 'opt -val <lit>' records (the canonical form) and,
    for blocks without any opt records, bare quoted comma lists. -doc prose is
    never quoted-literal data.
    """
    literals = []
    if re.search(r"\bopt\b", options_text):
        for match in re.finditer(
                r"-val\s+(?:'([^']*)'|\"([^\"]*)\"|([^\s{,]+))", options_text):
            lit = match.group(1) or match.group(2) or match.group(3)
            if lit and lit not in literals:
                literals.append(lit)
    else:
        for match in re.finditer(r"'([^']*)'|\"([^\"]*)\"", options_text):
            lit = match.group(1) or match.group(2)
            if lit and lit not in literals:
                literals.append(lit)
    return literals


def register(entries: dict, program: str, namelist: str, name: str,
             type_name: str | None, array_dims: str | None, body: str,
             inherited_type: str | None = None) -> None:
    """Upsert one .def var declaration into the per-version table."""
    key = name.lower()
    record = entries.setdefault(key, KeywordEntry(program=program, name=name,
                                                  namelist=namelist))
    eff_type = type_name if type_name else (record.type_name or inherited_type)
    if eff_type:
        record.type_name = eff_type
    if array_dims:
        record.array_dims = array_dims.strip()
    if body:
        status = grab(body, "status")
        if status and "REQUIRED" in status.upper():
            record.required = True
        default = grab(body, "default")
        if default is not None:
            record.default_by_version["_def"] = " ".join(default.split())
        options = grab(body, "options")
        if options:
            record.doc_options = parse_doc_options(options)


def scan_block(body: str, program: str, namelist: str, entries: dict,
               inherited_type: str | None, stats: dict) -> None:
    """Walk one .def block level; 'group' blocks recurse, vargroups propagate
    their -type to bare 'var NAME' member lines, cards are counted only."""
    pos = 0
    while pos < len(body):
        head = ENTRY_HEAD.search(body, pos)
        if not head:
            break
        kind, name, type_name = head.group(1), head.group(2), head.group(3)
        block_open = body.index("{", head.start())
        block_close = match_brace(body, block_open)
        inner = body[block_open + 1: block_close - 1]
        if kind == "var" and name:
            tail = body[head.start():block_open]
            dim_match = re.search(r"\(([^)]*)\)",
                                  tail[tail.find(name) + len(name):])
            register(entries, program, namelist, name, type_name,
                     dim_match.group(1) if dim_match else None,
                     inner, inherited_type)
            stats["vars"] += 1
        elif kind == "vargroup":
            for member in VARGROUP_MEMBER.finditer(inner):
                register(entries, program, namelist, member.group(1),
                         member.group(2) or type_name, member.group(3),
                         "", type_name)
                stats["vars"] += 1
        elif kind == "group":
            scan_block(inner, program, namelist, entries, type_name, stats)
        elif kind == "card":
            stats["cards"] += 1
        # dimension/multidimension/label carry bounds or prose only
        pos = block_close


def parse_def(text: str, program: str, entries: dict) -> dict:
    """Parse one INPUT_*.def grammar file into {key: KeywordEntry}."""
    text = strip_records(text)
    if text.count("{") != text.count("}"):
        raise ValueError("unbalanced brace totals in .def: %d vs %d"
                         % (text.count("{"), text.count("}")))
    stats = {"namelists": [], "cards": 0, "vars": 0}
    for nml in re.finditer(r"\bnamelist\s+([A-Za-z_][\w]*)\s*\{", text):
        namelist = nml.group(1).upper()
        stats["namelists"].append(namelist)
        open_index = text.index("{", nml.start())
        close_index = match_brace(text, open_index)
        scan_block(text[open_index + 1: close_index - 1], program, namelist,
                   entries, None, stats)
    return stats


# ------------------------------------------------- Fortran source mining

def strip_fortran_comments(text: str) -> str:
    """Strip trailing ! comments honouring single/double quotes."""
    out = []
    for raw in text.split("\n"):
        buf = []
        quote = None
        i = 0
        while i < len(raw):
            ch = raw[i]
            if quote:
                buf.append(ch)
                if ch == quote:
                    if i + 1 < len(raw) and raw[i + 1] == quote:
                        buf.append(raw[i + 1])
                        i += 1
                    else:
                        quote = None
            elif ch in "'\"":
                quote = ch
                buf.append(ch)
            elif ch == "!":
                break
            else:
                buf.append(ch)
            i += 1
        out.append("".join(buf))
    return "\n".join(out)


DECL_RE = re.compile(
    r"^\s*(CHARACTER|INTEGER|REAL|LOGICAL)\b"
    r"(?:\s*\([^)]*\))?\s*(?:::\s*)?(.+?)\s*$",
    re.IGNORECASE)


def parse_namelist_source(text: str) -> dict:
    """NAMELIST /X/ a, b(...) declarations -> {namelist: {var: (type, dims)}}.

    Continuation lines end with '&'; declaration lists are comma-split with
    per-item (dims) preserved. SAVE/EXTERNAL/parameter-like lines are ignored.
    """
    text = strip_fortran_comments(text)
    declarations: dict = {}
    for line in text.split("\n"):
        decl = DECL_RE.match(line)
        if not decl:
            continue
        type_name = decl.group(1).upper()
        rest = decl.group(2)
        if "::" not in line and "," not in rest:
            continue  # scalar function-local decl without '::' stays suspect;
        items = []
        depth = 0
        current = []
        for ch in rest:
            if ch == "," and depth == 0:
                items.append("".join(current))
                current = []
                continue
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            current.append(ch)
        items.append("".join(current))
        for item in items:
            item = item.strip()
            match = re.match(r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*"
                             r"(?:=[^,]*)?$", item)
            if not match:
                continue
            name = match.group(1).lower()
            dims = match.group(2).strip() if match.group(2) else None
            declarations[name] = (type_name, dims)
    namelists: dict = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        match = re.search(r"\bNAMELIST\s*/\s*([A-Za-z_]\w*)\s*/\s*(.*)$",
                          lines[i], re.IGNORECASE)
        if not match:
            i += 1
            continue
        namelist = match.group(1).upper()
        payload = match.group(2)
        while payload.rstrip().endswith("&") and i + 1 < len(lines):
            i += 1
            payload = payload.rstrip()[:-1] + " " + lines[i]
        members = namelists.setdefault(namelist, {})
        parts = []
        current = []
        depth = 0
        for ch in payload:
            if ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
                continue
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            current.append(ch)
        parts.append("".join(current))
        for part in parts:
            part = part.strip()
            member = re.match(r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*$", part)
            if not member:
                continue
            name = member.group(1).lower()
            dims = member.group(2).strip() if member.group(2) else None
            type_name, decl_dims = declarations.get(name, (None, None))
            members[name] = (type_name, dims or decl_dims)
        i += 1
    return namelists


def merge_namelist_source(namelists: dict, program: str, entries: dict) -> int:
    """Union source-declared NAMELIST membership into the mined table."""
    merged = 0
    for namelist, members in namelists.items():
        for name, (type_name, dims) in members.items():
            record = entries.setdefault(name, KeywordEntry(
                program=program, name=name, namelist=namelist))
            record.source_typed = True
            if type_name:
                record.type_name = type_name  # the compiled declaration wins
            if dims and not record.array_dims:
                record.array_dims = dims
            merged += 1
    return merged


def parse_select_cases(text: str) -> dict:
    """SELECT CASE literal arms -> {selector: {"literals": [...], "hard": bool}}.

    Arms with ranges (1:3) or non-literal expressions poison their selector
    (dropped - a range is not a finite literal set, and guessing is worse than
    admitting the gap). HARD means the CASE DEFAULT arm calls errore() - the
    program refuses out-of-set input. SOFT (silent remap or DEFAULT-free
    pass-through) means the binary tolerates/replaces out-of-set input, which
    changes the audit severity for those keywords. CASE DEFAULT never
    contributes literals. Fortran CHARACTER CASE is exact match, so literals
    are kept verbatim, case included.
    """
    joined = strip_fortran_comments(text)
    selectors: dict = {}
    stack: list = []
    for match in re.finditer(
            r"(?i)\bSELECT\s+CASE\s*\(([^)]*)\)|\bCASE\s*\(([^)]*)\)"
            r"|\bCASE\s+DEFAULT\b|\bEND\s+SELECT\b", joined):
        whole, select_expr, case_expr = match.group(0), match.group(1), match.group(2)
        if select_expr is not None:
            name = re.sub(r"(?i)\btrim\b|\badjustl\b|[()\s]", "",
                          select_expr).lower()
            stack.append({"name": name, "literals": [], "poisoned": False,
                          "default_start": None})
        elif re.match(r"(?i)\s*CASE\s+DEFAULT", whole):
            if stack:
                stack[-1]["default_start"] = match.start()
        elif case_expr is not None:
            if not stack:
                continue
            top = stack[-1]
            if ":" in case_expr:
                top["poisoned"] = True
                continue
            literals = re.findall(r"'([^']*)'|\"([^\"]*)\"|([+-]?\d+)",
                                  case_expr)
            flat = [a or b or c for a, b, c in literals]
            if not flat:
                top["poisoned"] = True
                continue
            for lit in flat:
                if lit not in top["literals"]:
                    top["literals"].append(lit)
        else:  # END SELECT
            if stack:
                done = stack.pop()
                if done["poisoned"]:
                    selectors.pop(done["name"], None)
                    continue
                default_arm = ""
                if done["default_start"] is not None:
                    default_arm = joined[done["default_start"]:match.start()]
                hard = "errore" in default_arm.lower()
                existing = selectors.setdefault(done["name"],
                                                {"literals": [], "hard": False})
                for lit in done["literals"]:
                    if lit not in existing["literals"]:
                        existing["literals"].append(lit)
                # A keyword reported hard if ANY of its switches refuses input
                existing["hard"] = existing["hard"] or hard
    return selectors


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mine_all(qe_src: Path) -> tuple:
    """Mine every version. Returns (union entries, per-version counts, hashes)."""
    provenance = []
    all_entries: dict = {}  # (program, key) -> KeywordEntry
    per_version_counts: dict = {}
    dropped_selectors: dict = {}
    for vi, version in enumerate(VERSIONS):
        vdir = qe_src / version
        if not vdir.is_dir():
            raise FileNotFoundError("missing QE grammar dir: " + str(vdir))
        for program, spec in PROGRAMS.items():
            def_path = vdir / spec["def_file"]
            provenance.append(("qe-%s" % version, spec["def_file"],
                               sha256_of(def_path)))
            version_entries: dict = {}
            stats = parse_def(def_path.read_text(errors="replace"), program,
                              version_entries)
            namelist_path = vdir / spec["namelist_source"]
            provenance.append(("qe-%s" % version, spec["namelist_source"],
                               sha256_of(namelist_path)))
            src_membership = parse_namelist_source(
                namelist_path.read_text(errors="replace"))
            merged = merge_namelist_source(src_membership, program,
                                           version_entries)
            case_selectors: dict = {}
            for case_file in spec["case_files"]:
                case_path = vdir / case_file
                provenance.append(("qe-%s" % version, case_file,
                                   sha256_of(case_path)))
                for name, switch in parse_select_cases(
                        case_path.read_text(errors="replace")).items():
                    bucket = case_selectors.setdefault(
                        name, {"literals": [], "hard": False})
                    for lit in switch["literals"]:
                        if lit not in bucket["literals"]:
                            bucket["literals"].append(lit)
                    bucket["hard"] = bucket["hard"] or switch["hard"]
            for key, record in version_entries.items():
                acc = all_entries.setdefault((program, key), KeywordEntry(
                    program=program, name=record.name, namelist=record.namelist))
                acc.mask |= (1 << vi)
                if record.type_name:
                    acc.type_name = record.type_name
                if record.array_dims and not acc.array_dims:
                    acc.array_dims = record.array_dims
                acc.required = acc.required or record.required
                acc.source_typed = acc.source_typed or record.source_typed
                label = VERSIONS[vi]
                if "_def" in record.default_by_version:
                    acc.default_by_version[label] = record.default_by_version["_def"]
                if record.doc_options and not acc.doc_options:
                    acc.doc_options = list(record.doc_options)
            for name, switch in case_selectors.items():
                acc = all_entries.get((program, name))
                if acc is None:
                    dropped_selectors.setdefault((program, name), set()).add(version)
                    continue
                target = acc.hard_literal_masks if switch["hard"] else acc.soft_literal_masks
                for lit in switch["literals"]:
                    target[lit] = target.get(lit, 0) | (1 << vi)
                acc.hard_enum = acc.hard_enum or switch["hard"]
            per_version_counts[(version, program)] = (
                len(version_entries), len(stats["namelists"]), stats["cards"],
                len(case_selectors), merged, len(src_membership))
    return all_entries, per_version_counts, provenance, dropped_selectors


def render_default(acc: KeywordEntry) -> str | None:
    """Uniform default text, or a per-version map string when it drifted."""
    present = [(VERSIONS[i], acc.default_by_version.get(VERSIONS[i]))
               for i in range(len(VERSIONS)) if acc.mask & (1 << i)]
    if not present:
        return None
    values = {val for _, val in present}
    if len(values) == 1:
        return present[0][1]
    # contiguous equal-value versions collapse into one first-last segment:
    # "[7.2-7.5: 4 * ecutwfc; 7.6: (none)]" - compact AND lossless.
    segments = []
    start_idx = 0
    for i in range(1, len(present) + 1):
        if i == len(present) or present[i][1] != present[start_idx][1]:
            first = present[start_idx][0]
            last = present[i - 1][0]
            value = present[start_idx][1]
            label = first if first == last else first + "-" + last
            segments.append("%s: %s" % (label, value if value is not None else "(none)"))
            start_idx = i
    return "[" + "; ".join(segments) + "]"


def java_string(text: str) -> str:
    return "\"" + text.replace("\\", "\\\\").replace("\"", "\\\"") + "\""


def masked_csv(masks: dict) -> str:
    """CSV of literals; a '~0xHH' suffix marks version-drift ones."""
    parts = []
    for lit, mask in masks.items():
        if mask == ALL_VERSION_MASK:
            parts.append(lit)
        else:
            parts.append("%s~0x%02X" % (lit, mask))
    return ",".join(parts)


def render_hard_literals(acc: KeywordEntry) -> str:
    """HARD accepted literals: every switch literal when any switch refuses."""
    if not acc.hard_enum:
        return ""
    merged = dict(acc.soft_literal_masks)
    for lit, mask in acc.hard_literal_masks.items():
        merged[lit] = merged.get(lit, 0) | mask
    return masked_csv(merged)


def render_soft_literals(acc: KeywordEntry) -> str:
    """SOFT accepted literals (remapped/pass-through), empty when the keyword
    is hard-enum everywhere (then they ride the hard list instead)."""
    if acc.hard_enum:
        return ""
    return masked_csv(acc.soft_literal_masks)


def emit_java(entries: dict, provenance: list) -> str:
    today = "2026-07-21"
    out = []
    out.append("/*")
    out.append(" * Copyright (C) 2025-2026 QuantumForge Development Team.")
    out.append(" */")
    out.append("// GENERATED FILE - DO NOT EDIT BY HAND.")
    out.append("// Generated " + today + " by scripts/qe_schema_miner.py from Quantum")
    out.append("// ESPRESSO ground-truth grammar files (tags qe-7.2 .. qe-7.6). Regenerate")
    out.append("// with: python3 scripts/qe_schema_miner.py --qe-src <dir-of-tagged-grammar>")
    out.append("// The ground-truth files are QA inputs only and are NOT vendored into")
    out.append("// this repository (Quantum ESPRESSO is GPL): only metadata FACTS are")
    out.append("// extracted (keyword names, namelist membership, declared types,")
    out.append("// declared defaults, REQUIRED flags, documented option literals, the")
    out.append("// exact literals each program's own Fortran SELECT CASE validation")
    out.append("// accepts - mined per version because the accepted set drifts - and")
    out.append("// per-version presence). No documentation prose is copied; descriptions")
    out.append("// stay at QE's own online docs, which QENamelistSchema links per program.")
    out.append("// Source fingerprints (sha256 over the exact bytes mined):")
    seen = set()
    for tag, fname, digest in provenance:
        if (tag, fname) in seen:
            continue
        seen.add((tag, fname))
        out.append("//   %-7s %-22s %s" % (tag, fname, digest))
    out.append("package quantumforge.input.schema;")
    out.append("")
    out.append("import java.util.ArrayList;")
    out.append("import java.util.List;")
    out.append("")
    out.append("/** Union metadata table mined from QE grammar: see QENamelistSchema. */")
    out.append("final class QESchemaData {")
    out.append("")
    out.append("    private QESchemaData() {")
    out.append("    }")
    out.append("")
    out.append("    static List<QENamelistSchema.Entry> buildEntries() {")
    out.append("        List<QENamelistSchema.Entry> entries = new ArrayList<>();")
    order = {"pw": 0, "ph": 1, "hp": 2}
    sorted_entries = sorted(entries.values(),
                            key=lambda e: (order[e.program], e.namelist, e.name.lower()))
    count = 0
    for acc in sorted_entries:
        count += 1
        dims_java = java_string(acc.array_dims) if acc.array_dims else "null"
        default_text = render_default(acc)
        default_java = java_string(default_text) if default_text is not None else "null"
        out.append("        entries.add(QENamelistSchema.entry(\"%s\", \"%s\", %s,"
                   " QENamelistSchema.Type.%s, %s, %s, %s, 0x%02X, %s, %s, %s));"
                   % (acc.program, acc.namelist, java_string(acc.name),
                      acc.type_name or "UNKNOWN", dims_java,
                      str(acc.required).lower(), default_java, acc.mask,
                      java_string(",".join(acc.doc_options)),
                      java_string(render_hard_literals(acc)),
                      java_string(render_soft_literals(acc))))
    out.append("        return entries;")
    out.append("    }")
    out.append("")
    out.append("    /** Mined entry count, pinned by QENamelistSchemaTest. */")
    out.append("    static final int ENTRY_COUNT = %d;" % count)
    out.append("}")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qe-src", required=True, type=Path,
                        help="directory containing the per-version grammar dirs")
    parser.add_argument("--output", type=Path,
                        default=Path("src/quantumforge/input/schema/QESchemaData.java"))
    parser.add_argument("--dump", action="store_true",
                        help="print the mined table instead of writing Java")
    args = parser.parse_args()

    entries, per_version_counts, provenance, dropped = mine_all(args.qe_src)
    if args.dump:
        for (version, program), row in sorted(per_version_counts.items()):
            print(("%s %-3s vars=%-4d namelists=%-3d cards=%-3d selectors=%-3d"
                   " src-merged=%-4d src-namelists=%d")
                  % ((version, program) + row))
        print("union entries:", len(entries))
        drifting = [e for e in sorted(entries.values(),
                                      key=lambda e: (e.program, e.name.lower()))
                    if e.mask != ALL_VERSION_MASK]
        print("version-drifting keywords (%d):" % len(drifting))
        for acc in drifting:
            present = [VERSIONS[i] for i in range(len(VERSIONS)) if acc.mask & (1 << i)]
            print("  %-3s %-28s %-12s present=%s"
                  % (acc.program, acc.name, acc.namelist, ",".join(present)))
        enums = [e for e in sorted(entries.values(),
                                   key=lambda e: (e.program, e.name.lower()))
                 if e.hard_literal_masks or e.soft_literal_masks or e.doc_options]
        print("enums (%d):" % len(enums))
        for acc in enums:
            print("  %-3s %-26s hard=%s" % (acc.program, acc.name,
                                            render_hard_literals(acc)))
            soft = render_soft_literals(acc)
            if soft:
                print("      soft=%s" % soft)
            if acc.doc_options:
                print("      doc=%s" % acc.doc_options[:8])
        print("selectors dropped (not namelist keywords): %d" % len(dropped))
        for (program, name), vers in sorted(dropped.items()):
            print("  %-3s %s in %s" % (program, name, sorted(vers)))
        return 0
    java = emit_java(entries, provenance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(java)
    print("wrote %s (%d entries)" % (args.output, len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
