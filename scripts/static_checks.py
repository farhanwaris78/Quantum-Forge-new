#!/usr/bin/env python3
"""Dependency-free repository consistency checks used before Maven/GUI tests."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def error(message: str) -> None:
    ERRORS.append(message)


def text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # report all files instead of stopping at the first
        error(f"{path.relative_to(ROOT)} is not valid UTF-8: {exc}")
        return ""


source_files = list((ROOT / "src").rglob("*.java"))
test_files = list((ROOT / "tests" / "java").rglob("*.java"))
all_java = source_files + test_files

# XML and text encoding.
for path in [ROOT / "pom.xml", *list((ROOT / "src").rglob("*.fxml"))]:
    try:
        ET.parse(path)
    except Exception as exc:
        error(f"invalid XML {path.relative_to(ROOT)}: {exc}")
for path in [*all_java, *list((ROOT / "src").rglob("*.css")),
             *list((ROOT / "src").rglob("*.prop"))]:
    text(path)

# ---------------------------------------------------------------------------
# Console / stack-trace / TODO hygiene bans (cycle 6, items 17.2-17.4).
# printStackTrace() writes to stderr, which is invisible in the packaged app;
# the replacement is AppLog.trace(cause). System.out is the CLI's own stdout
# contract in the launcher and the logging sink in AppLog; everywhere else it
# is app noise. A bare "// TODO" is a silent no-op and must be resolved.
# ---------------------------------------------------------------------------
PRINT_STACK_TRACE_ALLOW = {"AppLog.java", "CrashReporter.java"}
SYSTEM_OUT_ALLOW = {"AppLog.java", "QuantumForgeLauncher.java"}


def _is_comment_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*")


def print_stack_trace_count(content: str) -> int:
    count = 0
    for line in content.splitlines():
        if _is_comment_line(line):
            continue
        if "printStackTrace(" in line:
            count += 1
    return count


def system_out_count(content: str) -> int:
    count = 0
    for line in content.splitlines():
        if _is_comment_line(line):
            continue
        if "System.out." in line:
            count += 1
    return count


def bare_todo_count(content: str) -> int:
    return len(re.findall(r"(?m)//\s*TODO\s*(\r?$)", content))


for _path in source_files:
    _content = text(_path)
    if _path.name not in PRINT_STACK_TRACE_ALLOW:
        _n = print_stack_trace_count(_content)
        if _n:
            error(f"{_path.relative_to(ROOT)}: {_n} printStackTrace() call(s); "
                  f"use quantumforge.com.log.AppLog.trace(cause) instead")
    if _path.name not in SYSTEM_OUT_ALLOW:
        _n = system_out_count(_content)
        if _n:
            error(f"{_path.relative_to(ROOT)}: {_n} System.out use(s); "
                  f"route through quantumforge.com.log.AppLog instead")
    _n = bare_todo_count(_content)
    if _n:
        error(f"{_path.relative_to(ROOT)}: {_n} bare // TODO (no text after "
              f"the token); implement or remove it")

# Public top-level Java type/file and package/path agreement.
for path in all_java:
    content = text(path)
    public_type = re.search(
        r"(?m)^public\s+(?:final\s+|abstract\s+)?(?:class|interface|enum)\s+(\w+)", content
    )
    if public_type and public_type.group(1) != path.stem:
        error(f"{path.relative_to(ROOT)} declares public {public_type.group(1)}")
    package = re.search(r"(?m)^package\s+([\w.]+);", content)
    if package:
        source_root = ROOT / "src" if path in source_files else ROOT / "tests" / "java"
        expected = Path(*package.group(1).split(".")) / path.name
        if path.relative_to(source_root) != expected:
            error(f"{path.relative_to(ROOT)} does not match package {package.group(1)}")

# Internal imports resolve to a source/test type (nested types resolve through their owner).
for path in all_java:
    for imported in re.findall(
        r"(?m)^import\s+(?:static\s+)?(quantumforge(?:\.\w+)+)(?:\.\*)?;", text(path)
    ):
        parts = imported.split(".")
        resolved = False
        for length in range(len(parts), 1, -1):
            candidate = Path(*parts[:length]).with_suffix(".java")
            if (ROOT / "src" / candidate).exists() or (ROOT / "tests" / "java" / candidate).exists():
                resolved = True
                break
        if not resolved:
            error(f"{path.relative_to(ROOT)} has unresolved internal import {imported}")

# Version agreement.
pom = text(ROOT / "pom.xml")
version_source = text(ROOT / "src" / "quantumforge" / "ver" / "Version.java")
pom_version = re.search(r"<version>([^<]+)</version>", pom)
java_version = re.search(r'VERSION\s*=\s*"([^"]+)"', version_source)
versions = [pom_version.group(1) if pom_version else None,
            java_version.group(1) if java_version else None]
for prop in ["Environments.unix.prop", "Environments.win.prop"]:
    match = re.search(r"(?m)^version\s*=\s*(\S+)", text(ROOT / "src" / "quantumforge" / "com" / "env" / prop))
    versions.append(match.group(1) if match else None)
if None in versions or len(set(versions)) != 1:
    error(f"version declarations disagree: {versions}")

# Main FXML is manually controlled; every ID must be represented by the controller.
fxml = text(ROOT / "src" / "quantumforge" / "app" / "QEFXMain.fxml")
controller = text(ROOT / "src" / "quantumforge" / "app" / "QEFXMainController.java")
for identifier in set(re.findall(r'fx:id="([^"]+)"', fxml)):
    if not re.search(r"\b" + re.escape(identifier) + r"\b", controller):
        error(f"QEFXMain.fxml id {identifier} is absent from QEFXMainController")

# Local Markdown links and release documentation manifest.
for path in [ROOT / "README.md", *list((ROOT / "docs").glob("*.md"))]:
    for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text(path)):
        target = target.split("#", 1)[0]
        if target and "://" not in target and not (path.parent / target).resolve().exists():
            error(f"broken local link in {path.relative_to(ROOT)}: {target}")
required_docs = [
    "INSTALLATION.md", "RELEASE_AND_SECURITY.md", "SCIENTIFIC_SOFTWARE_GUIDE.md",
    "CODE_AUDIT.md", "ROADMAP.md",
]
for builder in [ROOT / "packaging" / "build-portable.sh", ROOT / "packaging" / "build-portable.ps1"]:
    content = text(builder)
    for document in required_docs:
        if document not in content:
            error(f"{builder.relative_to(ROOT)} does not package {document}")

# Scientific/credential regressions that must never return silently.
joined_source = "\n".join(text(path) for path in source_files)
for pattern, description in [
    (r"Mocking 5 iterations", "mock convergence loop"),
    (r"Mock constant for", "mock scientific constant"),
    (r"Simplified Debye model", "fabricated phonon thermodynamics"),
    (r"P4/mmm' \(Mock\)", "mock magnetic space group"),
    (r"private String password;", "serializable plaintext SSH password"),
]:
    if re.search(pattern, joined_source):
        error(f"forbidden regression found: {description}")

# A button handler whose ENTIRE body is a success dialog.
#
# 41 controls in the modeller announced things like "Super Lattice built
# successfully" or "lattice thermal conductivity (κ_L) calculations complete"
# while their handler contained nothing but the dialog: no cell was read,
# nothing computed, nothing written. That is the P0-5/P0-6 fabricated-result
# defect in its purest form, and it is worse than a crash because the user
# goes looking for output that never existed - or cites it.
#
# Only INFORMATION/CONFIRMATION dialogs count. A handler that exists purely to
# say "not implemented" is the honest case and uses WARNING/ERROR, so it is
# deliberately allowed.
_HANDLER = re.compile(
    r"setOnAction\(\s*\w+\s*->\s*\{(.*?)\n(\s*)\}\s*\);", re.S)
_ALERT_STMT = re.compile(
    r"Alert\s+\w+\s*=\s*new\s+Alert\([^;]*\);"
    r"|QEFXMain\.initializeDialogOwner\(\w+\);"
    r"|\w+\.set[A-Za-z]+\([^;]*\);"
    r"|\w+\.getDialogPane\(\)[^;]*;"
    r"|\w+\.showAndWait\(\);",
    re.S)

# Handlers whose whole job IS to display text, verified individually: a static
# help checklist and the capability-status matrix. Both present information
# rather than claiming that work was done, which is the distinction this check
# exists to enforce.
DIALOG_ONLY_HANDLER_BASELINE = {
    "src/quantumforge/app/QEFXMainController.java": 2,
}


def fake_success_setonaction_count(content: str) -> int:
    """Count setOnAction lambdas whose ONLY action is a success dialog."""
    found = 0
    for match in _HANDLER.finditer(content):
        body = re.sub(r"//.*", "", match.group(1))
        if "new Alert(" not in body:
            continue
        if not re.search(r"AlertType\.(INFORMATION|CONFIRMATION)", body):
            continue  # a refusal dialog is the honest case
        if _ALERT_STMT.sub("", body).strip():
            continue  # the handler also does real work
        found += 1
    return found


for path in source_files:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    content = text(path)
    found = fake_success_setonaction_count(content)
    allowed = DIALOG_ONLY_HANDLER_BASELINE.get(rel, 0)
    if found > allowed:
        error(f"{rel} has {found} button handler(s) whose only action is a "
              f"success dialog (baseline {allowed}); report real work or "
              f"refuse explicitly")

# The same defect reached through one level of indirection.
#
# The check above only sees dialogs written inline in a setOnAction lambda, so
# a click handler declared as a method slipped past it - which is exactly how
# QEFXBaderButton.onIconClicked() survived, telling the user "Bader charge
# analysis is calculating oxidation states..." with no Bader code in the tree.
# Click-entry methods are therefore checked by name too.
#
# Message helpers (showInfo/showError/...) are excluded: their whole purpose is
# to display text passed in by a caller that did the real work.
_CLICK_METHOD = re.compile(
    r"\n    (?:public|private|protected)\s+(?:static\s+)?void\s+"
    r"(onIconClicked|onClicked|onAction|handleClick|onButtonClicked)"
    r"\s*\([^)]*\)\s*\{(.*?)\n    \}", re.S)

def fake_success_clickmethod_count(content: str) -> int:
    """Count named click methods whose ONLY action is a success dialog."""
    found = 0
    if "new Alert(" not in content:
        return 0
    for match in _CLICK_METHOD.finditer(content):
        body = re.sub(r"//.*", "", match.group(2))
        if "new Alert(" not in body:
            continue
        if not re.search(r"AlertType\.(INFORMATION|CONFIRMATION)", body):
            continue
        if _ALERT_STMT.sub("", body).strip():
            continue
        found += 1
    return found


for path in source_files:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    content = text(path)
    found = fake_success_clickmethod_count(content)
    if found > 0:
        error(f"{rel} has {found} click method(s) that do nothing but show a "
              f"success dialog; report real work or refuse explicitly")

# FXML <-> controller binding consistency.
#
# The UI layer has no automated coverage, so a renamed fx:id or a controller
# field that no longer matches its markup is only discovered by clicking through
# the app at runtime. Two directions are checked:
#
#   1. an @FXML field with NO matching fx:id stays null after load, so the first
#      use is a NullPointerException - this is a genuine runtime bug;
#   2. an fx:id with no @FXML field is harmless to JavaFX but is dead markup,
#      usually the residue of a rename; existing ones are frozen as a baseline
#      so the count cannot grow.
#
# Controllers are wired programmatically here (no fx:controller attribute), via
# either `super("X.fxml", new XController(...))` or an FXMLLoader plus
# setController, so both conventions are resolved. @FXML fields are collected up
# the superclass chain: several controllers inherit e.g. `accordion`, and
# ignoring inheritance would report false failures.
# @FXML fields with no fx:id in their markup. All of these are guarded with a
# null check (usually an early return), so they are dead leftovers from removed
# controls rather than live NullPointerExceptions - verified individually before
# freezing. New ones are rejected, because an UNGUARDED field in this state does
# fail at runtime.
FXML_UNBOUND_FIELD_BASELINE = {
    "QEFXBandController": {"spinButton", "spinCombo", "spinLabel"},
    "QEFXModelerEditorController": {
        "applyStrainButton", "jiggleButton", "jiggleField", "smilesButton",
        "smilesField", "strainXField", "strainYField", "strainZField",
        "vacuumButton", "vacuumField"},
    "QEFXScfController": {"hybridPane"},
    "QEFXSplashController": {"commentLabel", "progressBar"},
    "QEFXWebController": {"backwardButton", "favoriteButton", "forwardButton"},
}

FXML_ID_BASELINE = {
    ("QEFXInputFile.fxml", "QEFXInputFileController"): {"resizeWrapper"},
    ("QEFXModelerEditor.fxml", "QEFXModelerEditorController"): {
        "latAField1", "latAField2", "latBField1",
        "latBField2", "latCField1", "latCField2"},
    ("QEFXPhonon.fxml", "QEFXPhononController"): {"nq1Field", "nq2Field"},
    ("QEFXScf.fxml", "QEFXScfController"): {"projectPane"},
}

_java_by_stem = {p.stem: p for p in source_files}
_FXML_FIELD = re.compile(
    r"@FXML\s+(?:public|private|protected)?\s*[A-Za-z0-9_.<>,\[\]\s]*?\s([A-Za-z0-9_]+)\s*;")


def _fxml_fields(cls, seen=None):
    """@FXML field names of cls plus every in-repo superclass."""
    if seen is None:
        seen = set()
    if cls in seen or cls not in _java_by_stem:
        return set()
    seen.add(cls)
    src = text(_java_by_stem[cls])
    names = set(_FXML_FIELD.findall(src))
    parent = re.search(r"class\s+" + re.escape(cls) + r"[^{]*?\bextends\s+([A-Za-z0-9_]+)", src)
    if parent:
        names |= _fxml_fields(parent.group(1), seen)
    return names


_fxml_pairs = {}
for _java in source_files:
    _t = text(_java)
    for _m in re.finditer(
            r'super\(\s*"([A-Za-z0-9_]+\.fxml)"\s*,\s*new\s+([A-Za-z0-9_]+)\s*\(', _t):
        _fxml_pairs.setdefault(_m.group(1), set()).add(_m.group(2))
    if "setController(this)" in _t:
        for _m in re.finditer(r'getResource\(\s*"([A-Za-z0-9_]+\.fxml)"', _t):
            _fxml_pairs.setdefault(_m.group(1), set()).add(_java.stem)
    _cm = re.search(r"setController\(\s*new\s+([A-Za-z0-9_]+)\s*\(", _t)
    if _cm:
        for _m in re.finditer(r'getResource\(\s*"([A-Za-z0-9_]+\.fxml)"', _t):
            _fxml_pairs.setdefault(_m.group(1), set()).add(_cm.group(1))

_fxml_by_name = {p.name: p for p in (ROOT / "src").rglob("*.fxml")}
for _name, _controllers in sorted(_fxml_pairs.items()):
    _path = _fxml_by_name.get(_name)
    if _path is None:
        continue
    _markup = text(_path)
    _ids = set(re.findall(r'fx:id="([A-Za-z0-9_]+)"', _markup))
    for _cls in sorted(_controllers):
        if _cls not in _java_by_stem:
            continue
        _fields = _fxml_fields(_cls)
        _allowed = FXML_ID_BASELINE.get((_name, _cls), set())
        _orphan_ids = sorted(_ids - _fields - _allowed)
        if _orphan_ids:
            error(f"{_name}: fx:id without an @FXML field in {_cls}: "
                  f"{', '.join(_orphan_ids)}")
        # An @FXML field with no fx:id is null after load -> NPE on first use.
        _own = set(_FXML_FIELD.findall(text(_java_by_stem[_cls])))
        _allowed_fields = FXML_UNBOUND_FIELD_BASELINE.get(_cls, set())
        _unbound = sorted(f for f in _own if f not in _ids and f not in _allowed_fields)
        if _unbound:
            error(f"{_cls}: @FXML field with no fx:id in {_name} (will be null): "
                  f"{', '.join(_unbound)}")

# Physical-conversion literals must come from a named constant, not be typed
# into a call site. The codebase carries two legitimate constant families -
# Constants.* (QE 2006 values) and QEUnits.* (CODATA 2018) - which differ at the
# 1e-8 relative level. That difference is scientifically negligible; the problem
# is maintainability: a pasted literal belongs to neither family, cannot be
# updated, and has already drifted (two Ry->meV copies disagreed with each other
# and with Constants). New occurrences are therefore rejected. The existing ones
# are listed as a frozen baseline so this check cannot silently grow.
CONVERSION_LITERALS = [
    (r"13\.6056[0-9]*", "Rydberg->eV"),
    (r"13605\.[0-9]+", "Rydberg->meV"),
    (r"0\.52917[0-9]*", "Bohr->Angstrom"),
    (r"8\.617333[0-9]*e-5", "Boltzmann eV/K"),
]

# path -> number of allowed pre-existing occurrences (frozen baseline).
CONVERSION_LITERAL_BASELINE = {
    "src/quantumforge/com/consts/Constants.java": 99,
    "src/quantumforge/com/math/QEUnits.java": 99,
    "src/quantumforge/com/units/Unit.java": 99,
    "src/quantumforge/app/project/viewer/result/special/ExcitonAnalyzer.java": 1,
    "src/quantumforge/app/project/viewer/result/special/PourbaixTool.java": 1,
    "src/quantumforge/builder/QECatMapMkmExporter.java": 1,
    "src/quantumforge/builder/QEDiffusionBarrierLink.java": 1,
    "src/quantumforge/run/ResultAnalysisService.java": 5,
    "src/quantumforge/run/parser/BoltzTrap2TraceParser.java": 2,
    "src/quantumforge/run/parser/CubeGridReader.java": 1,
    "src/quantumforge/run/parser/PhononDosThermodynamics.java": 1,
    "src/quantumforge/run/parser/QEBerryPolarizationParser.java": 1,
    "src/quantumforge/app/project/editor/input/convergence/ConvergenceSweepRunner.java": 1,
}

for path in source_files:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    content = text(path)
    hits = 0
    for pattern, _name in CONVERSION_LITERALS:
        hits += len(re.findall(pattern, content))
    allowed = CONVERSION_LITERAL_BASELINE.get(rel, 0)
    if hits > allowed:
        error(f"{rel} hardcodes {hits} physical-conversion literal(s) "
              f"(baseline {allowed}); derive it from Constants/QEUnits/Unit instead")

# The README capability matrix is generated from CapabilityRegistry.java; a
# hand-edit there (or a registry change without regenerating) is documentation
# drift, which is exactly what item B2 set out to make impossible.
try:
    import subprocess
    generator = ROOT / "scripts" / "generate_capability_matrix.py"
    if generator.is_file():
        result = subprocess.run(
            [sys.executable, str(generator), "--check"],
            capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode != 0:
            error("README capability matrix is stale; run "
                  "scripts/generate_capability_matrix.py")
except Exception as exc:  # never let the checker itself crash the build
    error(f"could not verify the capability matrix: {exc}")

# ---------------------------------------------------------------------------
# Self-test for the fake-success guard.
#
# The guard's heuristic (dialog-only handler detection) can be fooled in both
# directions: a real fake handler written in an unrecognised shape slips
# through, and an honest handler that does real work before its dialog gets
# flagged. These embedded snippets pin the boundary so a future edit of either
# the guard OR a handler it should have caught is visible in the same run.
# The rewritten crystal-viewer items (Upload/Import/Detect space group) are
# the live negative case: they do real work and then show a dialog, and the
# guard must not flag them - the self-test proves the shape the guard accepts.
# ---------------------------------------------------------------------------
_FAKE_SETONACTION = (
    'button.setOnAction(event -> {\n'
    '    Alert alert = new Alert(AlertType.INFORMATION);\n'
    '    alert.setHeaderText("Super Lattice built successfully");\n'
    '    alert.showAndWait();\n'
    '});\n'
)
_FAKE_CLICKMETHOD = (
    '\n'
    '    private void onIconClicked() {\n'
    '        Alert alert = new Alert(AlertType.INFORMATION);\n'
    '        alert.setContentText("Bader charge analysis is calculating..."\n'
    '                + " oxidation states");\n'
    '        alert.showAndWait();\n'
    '    }\n'
)
_REAL_WORK_THEN_DIALOG = (
    'button.setOnAction(event -> {\n'
    '    OperationResult<UploadResult> result = JupyterClient.uploadText(\n'
    '            base, token, fileName, cif);\n'
    '    if (result.isSuccess()) {\n'
    '        Alert alert = new Alert(AlertType.INFORMATION);\n'
    '        alert.setHeaderText("Upload successful");\n'
    '        alert.showAndWait();\n'
    '    }\n'
    '});\n'
)
_REFUSAL_DIALOG = (
    'button.setOnAction(event -> {\n'
    '    Alert alert = new Alert(AlertType.ERROR);\n'
    '    alert.setHeaderText("Not implemented");\n'
    '    alert.showAndWait();\n'
    '});\n'
)


def _selftest_fake_success_guard() -> None:
    # The guard must catch the two pure-fake shapes.
    if fake_success_setonaction_count(_FAKE_SETONACTION) != 1:
        error("self-test: the setOnAction fake-success detector missed a "
              "dialog-only handler")
    if fake_success_clickmethod_count(_FAKE_CLICKMETHOD) != 1:
        error("self-test: the click-method fake-success detector missed a "
              "dialog-only handler")

    # The guard must NOT catch real work followed by a success dialog, nor an
    # honest WARNING/ERROR refusal.
    if fake_success_setonaction_count(_REAL_WORK_THEN_DIALOG) != 0:
        error("self-test: a handler that does real work before its dialog was "
              "flagged as fake")
    if fake_success_setonaction_count(_REFUSAL_DIALOG) != 0:
        error("self-test: an ERROR refusal dialog was counted as a fake "
              "success")

    # Live regression: the three rewritten crystal-viewer items (EditorMenu)
    # do real work and must stay below their baseline. The whole-file check
    # above already enforces this; the explicit assert makes the intent
    # readable when it trips.
    editor_menu = ROOT / "src" / "quantumforge" / "atoms" / "viewer" / \
        "operation" / "editor" / "EditorMenu.java"
    if editor_menu.is_file():
        content = editor_menu.read_text(encoding="utf-8")
        total = (fake_success_setonaction_count(content)
                 + fake_success_clickmethod_count(content))
        if total != 0:
            error(f"self-test: EditorMenu.java has {total} dialog-only "
                  f"handler(s); the rewritten items must do real work")


_selftest_fake_success_guard()


# ---------------------------------------------------------------------------
# Self-test for the hygiene bans (printStackTrace / System.out / bare TODO).
# ---------------------------------------------------------------------------
_FAKE_TRACE = "try { x(); } catch (Exception e) { e.printStackTrace(); }\n"
_FAKE_TRACE_OK = "try { x(); } catch (Exception e) { AppLog.trace(e); }\n"
_FAKE_SYSOUT = "System.out.println(\"hello\");\n"
_FAKE_SYSOUT_OK = "AppLog.info(\"c\", \"hello\");\n"
_FAKE_TODO = "        // TODO\n"
_FAKE_TODO_OK = "        // TODO: implement the retry backoff (item 6.6)\n"


def _selftest_hygiene_bans() -> None:
    if print_stack_trace_count(_FAKE_TRACE) != 1:
        error("self-test: the printStackTrace detector missed a call site")
    if print_stack_trace_count(_FAKE_TRACE_OK) != 0:
        error("self-test: the printStackTrace detector flagged an AppLog.trace line")
    if print_stack_trace_count(" * {@code e.printStackTrace()} in javadoc") != 0:
        error("self-test: the printStackTrace detector flagged a comment line")
    if system_out_count(_FAKE_SYSOUT) != 1:
        error("self-test: the System.out detector missed a use")
    if system_out_count(_FAKE_SYSOUT_OK) != 0:
        error("self-test: the System.out detector flagged an AppLog line")
    if bare_todo_count(_FAKE_TODO) != 1:
        error("self-test: the bare-TODO detector missed '// TODO'")
    if bare_todo_count(_FAKE_TODO_OK) != 0:
        error("self-test: the bare-TODO detector flagged a TODO with text")


_selftest_hygiene_bans()

if ERRORS:
    for item in ERRORS:
        print(f"ERROR: {item}", file=sys.stderr)
    print(f"Static checks failed with {len(ERRORS)} error(s).", file=sys.stderr)
    raise SystemExit(1)
print(f"Static checks passed: {len(source_files)} source and {len(test_files)} test Java files.")
