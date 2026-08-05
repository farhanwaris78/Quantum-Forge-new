#!/usr/bin/env python3
"""Regenerate the README capability matrix from CapabilityRegistry.java.

The registry is the single source of truth (item B2). The README table used to
be hand-maintained and had drifted: it described SSH/HPC as "Unavailable" and
Symmetry as a Bravais helper only, while the registry recorded both as PARTIAL
with substantial machinery behind them.

The equivalent runtime output is `quantumforge --capability-matrix`; this script
exists so CI and contributors can regenerate/verify without a JDK.

    scripts/generate_capability_matrix.py           # rewrite README.md in place
    scripts/generate_capability_matrix.py --check   # fail if README is stale
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "src" / "quantumforge" / "capability" / "CapabilityRegistry.java"
README = ROOT / "README.md"

BEGIN = "<!-- BEGIN GENERATED CAPABILITY MATRIX -->"
END = "<!-- END GENERATED CAPABILITY MATRIX -->"

LABELS = {
    "SUPPORTED": "Supported",
    "PARTIAL": "Partial",
    "EXPERIMENTAL": "Experimental",
    "UNAVAILABLE": "Unavailable",
}


def _statements(body: str) -> list[str]:
    """Split the factory body into balanced `register(...)` statements."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    instr = False
    esc = False
    for ch in body:
        cur.append(ch)
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                out.append("".join(cur))
                cur = []
    return out


def _split_args(statement: str) -> list[str]:
    inner = statement[statement.index("(") + 1: statement.rindex(")")]
    args: list[str] = []
    depth = 0
    cur: list[str] = []
    instr = False
    esc = False
    for ch in inner:
        if instr:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
            cur.append(ch)
        elif ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    args.append("".join(cur))
    return [a.strip() for a in args]


def _literal(expr: str) -> str:
    """Concatenate the Java string literals in an expression."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', expr)
    return "".join(parts).replace('\\"', '"').replace("\\n", " ").strip()


def build_matrix() -> str:
    source = REGISTRY.read_text(encoding="utf-8")
    body = source.split("createCapabilities()", 1)[1].split(
        "private static void register", 1)[0]

    rows = ["| Area | Maturity | Status |", "|---|---|---|"]
    count = 0
    for statement in _statements(body):
        if "register(values" not in statement:
            continue
        args = _split_args(statement)
        if len(args) < 6:
            continue
        name = _literal(args[2])
        status = args[3].split(".")[-1].strip()
        if status not in LABELS:
            raise SystemExit(f"unknown CapabilityStatus: {status}")
        summary = _literal(args[4]).replace("|", "\\|")
        required = _literal(args[5]).replace("|", "\\|")
        cell = summary + (f" _Required next: {required}_" if required else "")
        rows.append(f"| {name} | **{LABELS[status]}** | {cell} |")
        count += 1

    if count == 0:
        raise SystemExit("no capabilities parsed from CapabilityRegistry.java")
    return "\n".join(rows) + "\n"


def render_block(matrix: str) -> str:
    return (
        f"{BEGIN}\n"
        "<!-- Generated from src/quantumforge/capability/CapabilityRegistry.java\n"
        "     by scripts/generate_capability_matrix.py. Do not edit by hand:\n"
        "     change the registry, then rerun the script. -->\n\n"
        f"{matrix}\n"
        f"{END}"
    )


def main() -> int:
    check = "--check" in sys.argv
    readme = README.read_text(encoding="utf-8")
    block = render_block(build_matrix())

    if BEGIN not in readme or END not in readme:
        print(f"README.md is missing the {BEGIN} / {END} markers", file=sys.stderr)
        return 1

    start = readme.index(BEGIN)
    end = readme.index(END) + len(END)
    updated = readme[:start] + block + readme[end:]

    if updated == readme:
        print("Capability matrix is up to date.")
        return 0
    if check:
        print("README capability matrix is STALE. Run "
              "scripts/generate_capability_matrix.py to regenerate.", file=sys.stderr)
        return 1
    README.write_text(updated, encoding="utf-8")
    print("Regenerated the README capability matrix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
