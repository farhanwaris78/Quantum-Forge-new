#!/usr/bin/env python3
"""Mine the QE pw.x CARD grammar from Modules/read_cards.f90 (qe-7.2..qe-7.6)
into generated Java (QE-integration roadmap R4).

Ground truth mined verbatim, per tag, refreshed per run:
  * the read_cards DISPATCH chain:
      ELSEIF ( trim(card) == 'X' ) THEN (+ verbatim condition incl. prog
      gates like `.and. ( prog == 'WA' )` / `.AND. trism`), the two
      FATAL_REMOVED cards (DIPOLE/ESR -> errore 'no longer existing'), and
      the ELSE fallback: a bare WRITE 'Warning: card ... ignored' - an
      unknown card name is TOLERATED and IGNORED, never a read error;
  * per option-bearing card subroutine, the IF/ELSEIF option-literal chain
      (matches("LIT", ...) first branch counts; imatches for HUBBARD), the
      K_POINTS band/plane suffix flags "_B"/"_C", and the ELSE-ARM
      disposition: FATAL (errore 'unknown option for X'), TOLERATED_DEFAULT
      (DEPRECATED infomsg + default assignment), or TOLERATED_SILENT_DEFAULT
      (a plain default assignment with no message);
  * verbatim konsistency facts: every ' two occurrences' errore, the
      K_POINTS automatic six-integer READ statement and its two range
      errore lines, and the HUBBARD projector sanity traps.

Per-literal/per-card presence across qe-7.2..qe-7.6 becomes the same 5-bit
mask scheme as the namelist miner. Everything the file does not state stays
UNKNOWN - no card content rule is invented.

Usage: python3 scripts/qe_card_schema_miner.py /dir/with/read_cards_*.f90
"""
import hashlib
import re
import sys
from pathlib import Path

VERSIONS = ["7.2", "7.3", "7.4", "7.5", "7.6"]

# card name -> its reader subroutine in read_cards.f90 (the harvest spans).
CARD_SUBS = {
    "ATOMIC_POSITIONS": "card_atomic_positions",
    "K_POINTS": "card_kpoints",
    "CELL_PARAMETERS": "card_cell_parameters",
    "REF_CELL_PARAMETERS": "card_ref_cell_parameters",
    "ATOMIC_FORCES": "card_atomic_forces",
    "ATOMIC_VELOCITIES": "card_ion_velocities",
    "OCCUPATIONS": "card_occupations",
    "HUBBARD": "card_hubbard",
    "SOLVENTS": "card_solvents",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def span_of(source: str, sub: str) -> str:
    start = re.search(rf"SUBROUTINE\s+{re.escape(sub)}\s*\(", source)
    if start is None:
        raise ValueError(sub)
    # QE terminates a few readers with a BARE `END SUBROUTINE` (e.g.
    # card_ion_velocities). read_cards.f90 module procedures have no
    # CONTAINS-internal procedures, so the first END SUBROUTINE - named
    # or bare - after the reader's start is its terminator.
    end = re.search(rf"END\s+SUBROUTINE(?:\s+{re.escape(sub)})?\b",
                    source[start.start():])
    if end is None:
        raise ValueError(sub)
    return source[start.start():start.start() + end.end()]


def parse_dispatch(source: str):
    """(card, condition, killed-with-errore?) in chain order."""
    start = source.index("SUBROUTINE read_cards")
    end = source.index("END SUBROUTINE read_cards", start)
    block = source[start:end]
    out = []
    for m in re.finditer(
            r"ELSEIF\s*\(\s*(trim\(card\)\s*==\s*'([A-Z_0-9]+)'.*?)\)\s*THEN"
            r"(.{0,320}?)(?=ELSEIF|ELSE\b|ENDIF)", block, re.DOTALL):
        condition = " ".join(m.group(1).split())
        body = m.group(3)
        killed = "CALL errore" in body
        warns = "' ignored'" in body
        warn_prog = ""
        if warns:
            # Which prog the arm's ignored-WRITE fires under: K_POINTS warns
            # only under 'CP', KSOUT processes then warns under 'PW'.
            guard = re.search(r"prog == '([A-Z0-9]+)'", body)
            warn_prog = guard.group(1) if guard else "ANY"
        out.append({"card": m.group(2), "condition": condition,
                    "killed": killed, "warns_ignored": warns,
                    "warn_prog": warn_prog})
    fallback_warn = "' ignored'" in block
    return out, fallback_warn


def parse_options(source: str, sub: str, card: str):
    """(options, traps, suffixes, disposition, bare, note) for one reader.

    Options: every i?matches literal whose IF/ELSEIF arm assigns a card
    variable. Traps: literals of an arm whose (comment-stripped) body calls
    errore without any `= '...'` assignment (HUBBARD sanity checks; an
    `.OR.` arm yields ALL its literals as traps). Suffix flags: K_POINTS
    "_B"/"_C" (nested single-line IFs, never THEN-arms).

    Disposition of the option-chain ELSE arm, read straight off the arm:
      FATAL                    - ELSE body calls errore;
      TOLERATED_DEFAULT        - ELSE body assigns a default + DEPRECATED
                                 infomsg (any unrecognised option string);
      TOLERATED_SILENT_DEFAULT - ELSE body assigns a default, no message;
      IGNORED                  - content-only reader: input_line is never
                                 matched, so an option string is never read.
    When the ELSE body discriminates the bare card name
    (`trim(adjustl(input_line)) /= 'CARD'` -> errore), the BARE branch gets
    its own reading: FATAL (HUBBARD's second errore), TOLERATED_DEFAULT
    (SOLVENTS DEPRECATED + '1/cell'), or TOLERATED_SILENT (ATOMIC_POSITIONS
    falls through without a message).
    """
    span = span_of(source, sub)
    options, traps = [], []
    chain = []  # ("O"|"T", literal) in exact IF-chain arm order (substring
    # matches() semantics make order decisive: the -ATOMIC trap sits BEFORE
    # the ATOMIC option, so "PSEUDO-ATOMIC" aborts - order is the truth).
    suffixes = []
    for flag in re.findall(r"matches\(\s*\"(_[A-Z])\"", span):
        if flag not in suffixes:
            suffixes.append(flag)
    last_end = None
    for m in re.finditer(
            r"(?:IF|ELSEIF)\s*\((.*?)\)\s*THEN"
            r"(.{0,600}?)(?=ELSEIF|ELSE\b|ENDIF)", span, re.DOTALL):
        condition = m.group(1)
        literals = [lit.strip() for lit in
                    re.findall(r"i?matches\(\s*\"([^\"]+)\"", condition)]
        if not literals:
            continue
        body = re.sub(r"!.*", "", m.group(2))
        is_trap = "CALL errore" in body and not re.search(r"=\s*'", body)
        for literal in literals:
            if literal.startswith("_"):
                continue
            kind = "T" if is_trap else "O"
            chain.append((kind, literal))
            if is_trap:
                if literal not in traps:
                    traps.append(literal)
            elif literal not in options:
                options.append(literal)
        last_end = m.end()

    disposition = "IGNORED" if not options and not traps else "UNKNOWN"
    bare = disposition
    note = ""
    if last_end is not None and re.match(r"\s*ELSE\b", span[last_end:]):
        else_region = span[last_end:]
        # Line-based balanced scan: consume the ELSE arm up to the option
        # chain's own ENDIF. Continuation lines (`&` at end) are joined so a
        # multi-line IF condition still ends with THEN on its logical line.
        raw_lines = re.sub(r"!.*", "", else_region).splitlines()
        logical = []
        for line in raw_lines[1:]:  # skip the `ELSE` line itself
            stripped = line.strip()
            if logical and logical[-1].rstrip().endswith("&"):
                logical[-1] = logical[-1].rstrip()[:-1] + " " + stripped
            else:
                logical.append(stripped)
        chain_lines = []
        depth = 1  # inside the chain's ELSE; the chain ENDIF closes at 0
        for stripped in logical:
            if not stripped:
                continue
            if stripped.startswith("ENDIF"):
                depth -= 1
                if depth == 0:
                    break
                chain_lines.append(stripped)
                continue
            chain_lines.append(stripped)
            if re.match(r"^(?:ELSE)?IF\b", stripped) and (
                    stripped.endswith("THEN")):
                depth += 1
        else_body = "\n".join(chain_lines)

        def classify(text: str):
            """(disposition, short note) read off a block's own statements."""
            if "CALL errore" in text:
                msg = re.search(r"unknown option for \w+", text)
                return ("FATAL", msg.group(0) if msg
                        else "errore in ELSE arm")
            assigns = re.findall(r"\w+\s*=\s*'([^']*)'", text)
            if "DEPRECATED" in text or assigns:
                values = list(dict.fromkeys(assigns))
                rendered = ("'" + "'/'".join(values) + "'"
                            + (" (prog-dependent)" if len(values) > 1
                               else "")) if values else ""
                if "DEPRECATED" in text:
                    return ("TOLERATED_DEFAULT",
                            f"DEPRECATED infomsg + defaulted to {rendered}"
                            if values else "DEPRECATED infomsg + defaulted")
                return ("TOLERATED_SILENT_DEFAULT",
                        f"defaulted to {rendered} silently"
                        if values else "defaulted silently")
            return ("TOLERATED_SILENT", "passes silently")

        discr = re.search(r"/=\s*'" + re.escape(card) + r"'", else_body)
        if discr:
            # Split the discrimination IF-block into unknown-option and
            # bare-name regions: IF (...) /= 'CARD' ) THEN <unknown>
            # [ELSE <bare>] ENDIF [<bare if no ELSE>]
            after = else_body[discr.end():]
            block_m = re.match(r"\s*\)\s*THEN(.*?)\bENDIF\b", after,
                               re.DOTALL)
            block = block_m.group(1) if block_m else after
            if re.search(r"^ELSE\b", block, re.MULTILINE):
                unknown_txt, bare_txt = re.split(r"^ELSE\b", block,
                                                 maxsplit=1,
                                                 flags=re.MULTILINE)
            else:
                unknown_txt = block
                bare_txt = after[block_m.end():] if block_m else ""
            disposition, unote = classify(unknown_txt)
            bare, bnote = classify(bare_txt)
            note = f"{unote}; bare card name: {bnote}"
        else:
            disposition, note = classify(else_body)
            bare = disposition
    return options, traps, suffixes, disposition, bare, note, chain


def parse_facts(source: str):
    facts = []
    # duplicate-card fatal erorres: ' two occurrences'
    for m in re.finditer(r"CALL errore\(\s*'[^']+',\s*&?\s*&?\s*' two occurrences[^']*'", source):
        text = " ".join(m.group(0).replace("&", " ").split())
        text = text.replace("  ", " ")
        if text not in facts:
            facts.append(text)
    return facts


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    indir = Path(sys.argv[1])
    sources = {}
    prints = {}
    for version in VERSIONS:
        path = indir / f"read_cards_{version}.f90"
        if not path.is_file():
            raise SystemExit(f"missing ground truth: {path}")
        sources[version] = path.read_text(encoding="utf-8", errors="replace")
        prints[version] = sha256(path)

    # Per-version mining, then masks.
    dispatch_by_version = {}
    options_by_version = {}
    for version, source in sources.items():
        dispatch, fallback = parse_dispatch(source)
        dispatch_by_version[version] = (dispatch, fallback)
        card_opts = {}
        for card, sub in CARD_SUBS.items():
            try:
                card_opts[card] = parse_options(source, sub, card)
            except ValueError:
                # Honest fallback: the reader subroutine is absent in this
                # tag (7-tuple shape kept identical to parse_options).
                card_opts[card] = ([], [], [], "UNKNOWN", "UNKNOWN",
                                   "no reader subroutine in this tag", [])
                print(f"note: {version} {card}: reader subroutine not found")
        options_by_version[version] = card_opts

    def mask_of(present_versions):
        mask = 0
        for i, version in enumerate(VERSIONS):
            if version in present_versions:
                mask |= 1 << i
        return mask

    def java_text(text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    # Dispatch cards (union): condition verbatim from the newest tag carrying
    # it; killed/warns flags unioned; per-card presence mask.
    all_cards = []
    for version in VERSIONS:
        for record in dispatch_by_version[version][0]:
            if record["card"] not in all_cards:
                all_cards.append(record["card"])

    out = []
    out.append("/* GENERATED by scripts/qe_card_schema_miner.py - do not hand-edit.")
    out.append(" * Mined from QE Modules/read_cards.f90 at tags qe-7.2 .. qe-7.6,")
    for version in VERSIONS:
        out.append(f" * {version}: sha256={prints[version]},")
    out.append(" * fetched 2026-07-21 from github.com/QEF/q-e (blob-filtered clone).")
    out.append(" * Provenance rules: dispatch chain verbatim (incl. prog gates); ELSE")
    out.append(" * fallback = 'Warning: card ... ignored' (unknown card tolerated, never a")
    out.append(" * read error); option literals from the matches/imatches IF-chains;")
    out.append(" * ELSE-arm dispositions FATAL / TOLERATED_DEFAULT / TOLERATED_SILENT_DEFAULT")
    out.append(" * come from the arm's own statements; content rules beyond the mined")
    out.append(" * facts stay with QEInputValidator. */")
    out.append("package quantumforge.input.schema;")
    out.append("")
    out.append("import java.util.ArrayList;")
    out.append("import java.util.List;")
    out.append("")
    out.append("/** Generated mined QE card-grammar table (qe-7.2..7.6 read_cards.f90). */")
    out.append("final class QECardSchemaData {")
    out.append("")
    out.append("    static List<QECardSchema.Dispatch> buildDispatch() {")
    out.append("        List<QECardSchema.Dispatch> out = new ArrayList<>();")
    for card in all_cards:
        present = [v for v in VERSIONS
                   if any(r["card"] == card for r in dispatch_by_version[v][0])]
        newest = present[-1]
        record = next(r for r in dispatch_by_version[newest][0] if r["card"] == card)
        killed = str(record["killed"]).lower()
        out.append(f'        out.add(QECardSchema.dispatch("{card}",'
                   f' {java_text(record["condition"])}, {killed},'
                   f' {java_text(record["warn_prog"])}, 0x{mask_of(present):02X}));')
    out.append("        return out;")
    out.append("    }")
    out.append("")
    out.append("    static List<QECardSchema.CardGrammar> buildGrammars() {")
    out.append("        List<QECardSchema.CardGrammar> out = new ArrayList<>();")
    for card in CARD_SUBS:
        chain_masks = {}
        chain_order = []
        suffix_masks = {}
        for version in VERSIONS:
            _literals, _traps, suffixes, _disp, _bare, _note, chain = (
                options_by_version[version][card])
            for kind, literal in chain:
                key = f"{kind}:{literal}"
                if key not in chain_masks:
                    chain_order.append(key)
                chain_masks.setdefault(key, set()).add(version)
            for suffix in suffixes:
                suffix_masks.setdefault(suffix, set()).add(version)
        readings = {(options_by_version[v][card][3],
                     options_by_version[v][card][4],
                     options_by_version[v][card][5]) for v in VERSIONS}
        if len(readings) == 1:
            disposition, bare, note = next(iter(readings))
            disp_repr = (f'{java_text(disposition)}, 0x1F,'
                         f' {java_text(bare)}, 0x1F, {java_text(note)}')
        else:
            # disposition/bare per version: freshest reading + drift text
            freshest = options_by_version[VERSIONS[-1]][card]
            drift = "; ".join(
                f"{v}: {options_by_version[v][card][3]}/"
                f"{options_by_version[v][card][4]}" for v in VERSIONS)
            disp_repr = (f'{java_text(freshest[3])}, 0x1F,'
                         f' {java_text(freshest[4])}, 0x1F,'
                         f' {java_text("drifted: " + drift)}')
        chain_csv = ",".join(f"{key}~0x{mask_of(chain_masks[key]):02X}"
                             for key in chain_order)
        suffix_csv = ",".join(f"{suffix}~0x{mask_of(vs):02X}"
                              for suffix, vs in suffix_masks.items())
        out.append(f'        out.add(QECardSchema.grammar("{card}", {disp_repr},'
                   f' "{chain_csv}", "{suffix_csv}"));')
    out.append("        return out;")
    out.append("    }")
    out.append("")
    out.append("    /** Verbatim mined facts (bounded): duplicate-card erorres,"
               " K_POINTS automatic mesh rules, HUBBARD projector traps. */")
    out.append("    static List<String> buildFacts() {")
    facts = []
    for version in (VERSIONS[-1],):
        facts.extend(parse_facts(sources[version]))
    kc = span_of(sources[VERSIONS[-1]], "card_kpoints")
    mesh = re.search(r"READ\(input_line, \*, END=10, ERR=20\) ([^\n]+)", kc)
    if mesh:
        facts.append("K_POINTS automatic mesh: READ(input_line, *, END=10, ERR=20) "
                     + " ".join(mesh.group(1).split()))
    for cond in ("k1 < 0", "nk1 <= 0"):
        start = kc.find(cond)
        if start >= 0:
            m = re.search(r"CALL\s+errore\s*&?\s*\(\s*'[^']*'\s*,\s*&?\s*&?\s*'([^']*)'",
                          kc[start:start + 400])
            if m:
                facts.append("K_POINTS automatic constraint: "
                             + " ".join(m.group(1).split()))
    hub = span_of(sources[VERSIONS[-1]], "card_hubbard")
    if "Wrong name of the Hubbard projectors" in hub:
        facts.append("HUBBARD trap: misspelled/dash-less projector names abort with"
                     " 'Wrong name of the Hubbard projectors'")
    if "unknown option for HUBBARD" in hub:
        facts.append("HUBBARD unknown option aborts with 'unknown option for HUBBARD'")
    seen = []
    for fact in facts:
        if fact not in seen:
            seen.append(fact)
    out.append("        return List.of(")
    for index, fact in enumerate(seen[:16]):
        comma = "," if index < len(seen[:16]) - 1 else ""
        out.append(f'            {java_text(fact)}{comma}')
    out.append("        );")
    out.append("    }")
    out.append("}")

    target = Path("src/quantumforge/input/schema/QECardSchemaData.java")
    target.write_text("\n".join(out) + "\n", encoding="utf-8", newline="")
    print(f"dispatch cards: {len(all_cards)}, grammar cards: {len(CARD_SUBS)},"
          f" facts: {len(seen[:16])} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
