#!/usr/bin/env python3
"""Structural compile-readiness checks when javac is unavailable.

Validates packages, public type names, balanced braces (string/comment-aware),
required abstract method implementations, and recovery menu wiring.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests" / "java"
ERRORS: list[str] = []


def error(msg: str) -> None:
    ERRORS.append(msg)


def strip_strings_and_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            out.append('""')
            continue
        if ch == "'":
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "'":
                    i += 1
                    break
                i += 1
            out.append("''")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_file(path: Path, source_root: Path) -> None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_strings_and_comments(raw)
    if text.count("{") != text.count("}"):
        error(
            f"brace mismatch {path.relative_to(ROOT)} "
            f"{{ {text.count('{')} }} {text.count('}')}"
        )

    package = re.search(r"(?m)^package\s+([\w.]+);", raw)
    if not package:
        error(f"missing package {path.relative_to(ROOT)}")
        return
    expected_dir = source_root.joinpath(*package.group(1).split("."))
    if path.parent != expected_dir:
        error(f"package path mismatch {path.relative_to(ROOT)} vs {package.group(1)}")

    public = re.search(
        r"(?m)^public\s+(?:final\s+|abstract\s+)?(?:class|interface|enum)\s+(\w+)",
        raw,
    )
    if public and public.group(1) != path.stem:
        error(f"public type {public.group(1)} != file {path.name}")


def build_type_index(files):
    """Maps repo simple type names (top-level and nested) to (package, owner) tuples.

    Nested types are registered both on their own name and are considered
    accessible when their top-level owner is accessible (Outer.Inner usage).
    """
    index: dict[str, list[tuple[str, str | None]]] = {}
    for path in files:
        root = SRC if SRC in path.parents else TESTS
        rel = path.relative_to(root).with_suffix("")
        package = ".".join(rel.parent.parts)
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = strip_strings_and_comments(raw)
        top = None
        for match in re.finditer(r"(?:^|[}\s])(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)", text):
            name = match.group(1)
            if top is None:
                top = name
                owner = None
            else:
                owner = top
            index.setdefault(name, []).append((package, owner))
        if top is None:
            index.setdefault(path.stem, []).append((package, None))
    return index


def check_repo_type_imports(files, index):
    """Flags references to same-repository types that are not imported or otherwise
    accessible. External (JDK/JavaFX/third-party) types cannot be resolved without
    javac and are intentionally skipped.

    A name is accessible when any of these holds:
      * the file itself declares it (top-level or nested);
      * it lives in the same package;
      * it is imported exactly, or via a wildcard import of its package;
      * it is a nested type whose top-level owner is accessible by these rules;
      * an explicit non-repo import shadows the simple name.
    """
    java_lang = {
        "Boolean", "Byte", "Character", "Class", "Double", "Enum", "Exception",
        "Float", "IllegalArgumentException", "IllegalStateException", "Integer",
        "InterruptedException", "Long", "Math", "NullPointerException", "Number",
        "NumberFormatException", "Object", "Override", "RuntimeException",
        "Short", "String", "StringBuilder", "SuppressWarnings", "System",
        "Thread", "Throwable", "Void",
    }
    for path in files:
        root = SRC if SRC in path.parents else TESTS
        package = ".".join(path.relative_to(root).parent.parts)
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = strip_strings_and_comments(raw)

        own_names = set(re.findall(r"(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)", text))
        exact_imports: set[str] = set()
        wildcard_packages: set[str] = set()
        for imp in re.findall(r"(?m)^import\s+(?:static\s+)?([\w.]+?)(\.\*)?;", text):
            target, star = imp
            if star:
                wildcard_packages.add(target)
            else:
                exact_imports.add(target.rsplit(".", 1)[-1])

        # Inline fully-qualified uses (parseTree.Java types embedded in code)
        # need no import; remove them before token scanning.
        code = re.sub(r"\bquantumforge(?:\.[A-Za-z_]\w*)+", " ", text)
        code = re.sub(r"(?m)^\s*(?:import|package)\s+[\w.]+\s*;.*$", " ", code)

        declared = own_names | {path.stem}

        def accessible(name: str, depth: int = 0) -> bool:
            if name in declared or name in exact_imports or name in java_lang:
                return True
            entries = index.get(name)
            if not entries:
                return True  # external type: cannot verify here
            for pkg, owner in entries:
                if pkg == package or pkg in wildcard_packages:
                    return True
            if depth < 1:
                for pkg, owner in entries:
                    if owner and accessible(owner, depth + 1):
                        return True
            return False

        for token in set(re.findall(r"\b([A-Z][A-Za-z0-9_]{2,})\b", code)):
            entries = index.get(token)
            if not entries:
                continue  # not a repo type; JDK/JavaFX names are unverifiable here
            # Dot-qualified member uses (Outer.Inner, Map.Entry, FQN chains) are
            # resolved through their owner; only standalone uses need an import.
            if all(m.start() > 0 and code[m.start() - 1] == "."
                   for m in re.finditer(rf"(?<![\w]){re.escape(token)}\b", code)):
                continue
            if not accessible(token):
                locations = ", ".join(sorted({pkg for pkg, _ in entries}))
                error(
                    f"{path.relative_to(ROOT)} references repository type '{token}' "
                    f"(declared in {locations}) without an import or same-package access"
                )


# Known JDK exception hierarchy edges we can check without a compiler. Java
# rejects a multi-catch whose alternatives are related by subclassing
# ("Alternatives in a multi-catch statement cannot be related by subclassing"),
# and that is a hard compile error the structural checks above cannot see.
_EXCEPTION_PARENTS = {
    "IllegalArgumentException": {"RuntimeException", "Exception", "Throwable"},
    "IllegalStateException": {"RuntimeException", "Exception", "Throwable"},
    "NullPointerException": {"RuntimeException", "Exception", "Throwable"},
    "NumberFormatException": {"IllegalArgumentException", "RuntimeException",
                              "Exception", "Throwable"},
    "IndexOutOfBoundsException": {"RuntimeException", "Exception", "Throwable"},
    "ClassCastException": {"RuntimeException", "Exception", "Throwable"},
    "UnsupportedOperationException": {"RuntimeException", "Exception", "Throwable"},
    "ArithmeticException": {"RuntimeException", "Exception", "Throwable"},
    "ConcurrentModificationException": {"RuntimeException", "Exception", "Throwable"},
    "RuntimeException": {"Exception", "Throwable"},
    "IOException": {"Exception", "Throwable"},
    "FileNotFoundException": {"IOException", "Exception", "Throwable"},
    "InterruptedException": {"Exception", "Throwable"},
    "NoSuchAlgorithmException": {"Exception", "Throwable"},
    "CloneNotSupportedException": {"Exception", "Throwable"},
    "Exception": {"Throwable"},
    "LinkageError": {"Error", "Throwable"},
    "Error": {"Throwable"},
}


def check_multicatch(path: Path, text: str) -> None:
    """Reject `catch (A | B ...)` where one alternative subclasses another."""
    for match in re.finditer(r"catch\s*\(([^)]*\|[^)]*)\)", text):
        clause = match.group(1)
        # Strip the variable name and any annotations/final modifier.
        types = []
        for part in clause.split("|"):
            part = part.strip().replace("final ", "")
            tokens = part.split()
            if not tokens:
                continue
            # "java.io.IOException e" -> IOException
            types.append(tokens[0].split(".")[-1])
        for i, a in enumerate(types):
            for j, b in enumerate(types):
                if i == j:
                    continue
                if b in _EXCEPTION_PARENTS.get(a, set()):
                    line = text[: match.start()].count("\n") + 1
                    error(
                        f"{path.relative_to(ROOT)}:{line} multi-catch alternatives "
                        f"cannot be related by subclassing ({a} is a {b})"
                    )


def main() -> int:
    files = list(SRC.rglob("*.java")) + list(TESTS.rglob("*.java"))
    type_index = build_type_index(files)
    for path in files:
        root = SRC if SRC in path.parents else TESTS
        check_file(path, root)
        check_multicatch(path, path.read_text(encoding="utf-8"))
    check_repo_type_imports(files, type_index)

    project = (SRC / "quantumforge/project/Project.java").read_text(encoding="utf-8")
    if "exportQEInputsTo" not in project:
        error("Project missing exportQEInputsTo")
    for rel in [
        "quantumforge/project/ProjectBody.java",
        "quantumforge/project/ProjectProxy.java",
    ]:
        text = (SRC / rel).read_text(encoding="utf-8")
        if "exportQEInputsTo" not in text:
            error(f"{rel} missing exportQEInputsTo implementation")

    item_set = (SRC / "quantumforge/app/project/viewer/ViewerItemSet.java").read_text(
        encoding="utf-8"
    )
    actions = (SRC / "quantumforge/app/project/viewer/ViewerActions.java").read_text(
        encoding="utf-8"
    )
    if "recoverItem" not in item_set or "getRecoverItem" not in item_set:
        error("ViewerItemSet missing recover item")
    if "actionRecover" not in actions or "RecoveryAction" not in actions:
        error("ViewerActions missing recovery wiring")

    for rel in [
        "quantumforge/run/QECommandDag.java",
        "quantumforge/run/RestartManager.java",
        "quantumforge/run/WorkflowExporter.java",
        "quantumforge/run/ArtifactScanner.java",
        "quantumforge/run/DryRunPreflight.java",
        "quantumforge/tools/XCrySDenLauncher.java",
        "quantumforge/app/project/viewer/recovery/RecoveryAction.java",
        "quantumforge/ssh/KnownHostsStore.java",
        "quantumforge/ssh/JschSshTransport.java",
        "quantumforge/hpc/SlurmSchedulerAdapter.java",
        "quantumforge/hpc/SiteProfile.java",
        "quantumforge/symmetry/SpglibService.java",
        "quantumforge/app/ssh/HostKeyAcceptance.java",
        "quantumforge/ssh/SyncChecksumCache.java",
        "quantumforge/symmetry/SeekPathResult.java",
        "quantumforge/symmetry/StandardizedCell.java",
        "quantumforge/hpc/RemoteJobMonitor.java",
        "quantumforge/com/secrets/WindowsCredentialBackend.java",
        "quantumforge/run/parser/PhononDosThermodynamics.java",
        "quantumforge/run/CheckpointResubmit.java",
        "quantumforge/builder/neb/NEBPathCreator.java",
        "quantumforge/run/parser/QeXmlResultParser.java",
        "quantumforge/com/secrets/ProcessKeyringBackend.java",
        "quantumforge/hpc/JobQueueStore.java",
        "quantumforge/hpc/SgeSchedulerAdapter.java",
        "quantumforge/ssh/JobCancellation.java",
        "quantumforge/ssh/SelectiveResultSync.java",
        "quantumforge/hpc/ResultSyncManifest.java",
        "quantumforge/hpc/PbsSchedulerAdapter.java",
    ]:
        text = (SRC / rel).read_text(encoding="utf-8")
        if "class " not in text and "enum " not in text:
            error(f"{rel} does not declare a type")

    actions = (SRC / "quantumforge/app/project/viewer/ViewerActions.java").read_text(encoding="utf-8")
    if ("actionXcrysden" not in actions or "actionExportWorkflow" not in actions
            or "actionValidateInput" not in actions or "actionDiagnoseLog" not in actions
            or "actionAnalyzeBandGap" not in actions or "actionPreviewFinalGeometry" not in actions
            or "actionInspectPdos" not in actions or "actionInspectPhonons" not in actions
            or "actionInspectSpectra" not in actions or "actionDensityDifference" not in actions
            or "actionAnalyzeResults" not in actions):
        error("ViewerActions missing required export, validation, diagnosis, band-gap, geometry-preview, PDOS, phonon, spectra, density, or result-analysis actions")
    for rel in [
        "quantumforge/run/ResultAnalysisService.java",
        "quantumforge/app/project/viewer/analysis/AnalysisAction.java",
    ]:
        text = (SRC / rel).read_text(encoding="utf-8")
        if "class " not in text and "enum " not in text:
            error(f"{rel} does not declare a type")
    service = (SRC / "quantumforge/run/ResultAnalysisService.java").read_text(encoding="utf-8")
    for token in ["QEBandsDataParser", "QEMagneticMomentParser", "QEBornChargeDielectricParser",
                  "QEHubbardHpParser", "QETurboSpectrumParser", "QEXSpectraXanesParser",
                  "QEGipawNmrParser", "QEPwcondConductanceParser", "QEWannier90SpreadParser",
                  "QEThermoPwEosParser", "QEPhono3pyKappaParser", "QEEliashbergTcCalculator",
                  "QEPpChargePotentialBuilder", "QEPpWavefunctionBuilder",
                  "QEAcousticSumRuleValidator"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["DryRunPreflight", "RestartManager", "QEScratchStoragePolicy",
                  "QEResourceEstimator", "QEMpiTopologyAdvisor", "RunManifest",
                  "GeometryMeasurer", "QEMdDiffusionMsdParser", "QEHullThermodynamics"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["QEBerryPolarizationParser", "QESlabPlateauDiagnostic",
                  "QECarParrinelloParser", "MagneticSpaceGroupDetector",
                  "CubeGridReader", "QECitationManager",
                  "ScfConvergenceAnalyzer", "QETimingResourceParser",
                  "QESmearingConvergenceAnalyzer", "PhononDosThermodynamics",
                  "ElasticParser", "QEElasticStabilityValidator", "QELammpsThermoParser"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["GeometryConvergenceValidator", "PseudoFamilyValidator",
                  "SpglibService", "QeXmlResultParser",
                  "QEVasprunXmlParser", "QECastepLogParser"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["QEInputDiffPreview", "QEKpointMeshAdvisor", "QEPointDefectBuilder"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["QETensorAnalyzer", "QEDynmatModesParser", "QEBatteryVoltage",
                  "MoleculeAdsorber"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["SiteProfileValidator", "SiteProfile"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    text = (SRC / "quantumforge/hpc/SiteProfileValidator.java").read_text(encoding="utf-8")
    if "class " not in text:
        error("quantumforge/hpc/SiteProfileValidator.java does not declare a type")
    for token in ["MlModelManifest"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for token in ["QEExxPlanner"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    rel = "quantumforge/input/QEExxPlanner.java"
    text = (SRC / rel).read_text(encoding="utf-8")
    if "class " not in text:
        error(f"{rel} does not declare a type")
    for token in ["QEBrillouinZoneGeometry", "BandGapParser", "QEPdosParser"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    rel = "quantumforge/symmetry/QEBrillouinZoneGeometry.java"
    text = (SRC / rel).read_text(encoding="utf-8")
    if "class " not in text:
        error(f"{rel} does not declare a type")
    rel = "quantumforge/export/SvgSeriesPlotter.java"
    text = (SRC / rel).read_text(encoding="utf-8")
    if "class " not in text:
        error(f"{rel} does not declare a type")
    if "SvgSeriesPlotter" not in (SRC / "quantumforge/app/project/viewer/analysis/AnalysisAction.java").read_text(encoding="utf-8"):
        error("AnalysisAction is not wired to SvgSeriesPlotter SVG export")
    for token in ["MethodsTextBuilder", "RoCrateExporter", "QEThermochemistryMath",
                  "QEDiffusionBarrierLink", "EffectiveMassTensor", "SymmetricEigen3",
                  "QEConstraintSpec", "QEIonicConstraintManager",
                  "PhonopyForceSetsReader", "QEPhonopyForceSetsWriter",
                  "TrajectoryIndexReader", "ExtXyzDatasetValidator",
                  "EnergySeriesComparer", "TENSOR_EIGEN",
                  "PhononFrameSynthesis", "PHONON_MODE_FRAMES",
                  "HyperfineMapper", "HYPERFINE_LOOKUP",
                  "QEKeywordHelp", "KEYWORD_HELP",
                  "ArraySweepPlanner", "ARRAY_SWEEP_PLAN", "ArrayDeckTemplate",
                  "ArrayTaskIntent", "ArraySubmitPlan",
                  "ExtXyzCellExporter", "CELL_EXTXYZ_EXPORT",
                  "QERamanIRSpectraParser", "RAMAN_IR_SPECTRUM",
                  "TrajectoryWindowReader", "TRAJECTORY_WINDOW_SCAN",
                  "TENSOR_DIRECTIONAL", "QEGridDensityDifference",
                  "DENSITY_DIFFERENCE", "SupercellMatrixValidator",
                  "SUPERCELL_PREVIEW", "QEHubbardPlanner",
                  "HUBBARD_HP_DRAFT", "QETimingParser", "TIMING_RESOURCE",
                  "WorkspaceLightIndex", "WORKSPACE_SEARCH",
                  "QEWorkflowTemplateLibrary", "TEMPLATE_LIBRARY",
                  "PoscarStructureReader", "POSCAR_REVIEW",
                  "ELateTensorDraft", "ELASTIC_ELATE_DRAFT",
                  "SPIN_CUBE_MAGNETIZATION",
                  "QEEsmAuditor", "ESM_SLAB_CHECK",
                  "MoireTwistMath", "MOIRE_TWIST_PREVIEW",
                  "PdbStructureReader", "PDB_REVIEW",
                  "LammpsDataReader", "LAMMPS_DATA_REVIEW",
                  "CpInputPlanner", "CP_INPUT_DRAFT",
                  "Wannier90WinPlanner", "W90_WIN_DRAFT",
                  "CslSigmaMath", "GB_CSL_PREVIEW",
                  "QEVersionRuleCatalog", "QE_VERSION_CHECK",
                  "PoolDivisorMath", "MPI_POOLS_ADVISOR",
                  "QEUnits", "UNIT_CONVERT",
                  "QEErrorSignatureCatalog", "LOG_ERROR_DIAGNOSIS",
                  "XspectraInputPlanner", "XSPECTRA_INPUT_DRAFT",
                  "GipawInputPlanner", "GIPAW_INPUT_DRAFT",
                  "SlabMillerMath", "SLAB_MILLER_PREVIEW",
                  "CifStructureReader", "CIF_REVIEW",
                  "SdfStructureReader", "MOL_SDF_REVIEW",
                  "TurboLanczosInputPlanner", "TDDFPT_INPUT_DRAFT",
                  "CompositionalBaselineMath", "ML_DATASET_BASELINE",
                  "SeriesAlignmentMath", "SERIES_REF_ALIGN",
                  "BandsFermiReviewMath", "BANDS_FERMI_REVIEW",
                  "BandGapBandMath", "BAND_GAP_BANDS",
                  "TransformJournal", "PROVENANCE_JOURNAL_REVIEW",
                  "JobDbSchema", "JOB_DB_SCHEMA_PLAN",
                  "OptimadeQueryBuilder", "OPTIMADE_QUERY_DRAFT",
                  "OccupationLevelsParser", "OCCUPATION_LEVELS_REVIEW",
                  "MpApiQueryBuilder", "MP_QUERY_DRAFT",
                  "SshTargetSpec", "SSH_CONFIG_DRAFT",
                  "SftpTransferPlan", "SFTP_TRANSFER_PLAN",
                  "OptimadeStructuresParser", "OPTIMADE_RESPONSE_PARSE",
                  "MpSummaryParser", "MP_SUMMARY_PARSE",
                  "SlurmScriptBuilder", "SLURM_SCRIPT_DRAFT",
                  "KMeshConvergenceLadder", "KMESH_CONVERGENCE_PLAN",
                  "SiteProfileSpec", "SITE_PROFILE_DRAFT", "ContainerLaunchBridge",
                  "NebInputPlanner", "NEB_INPUT_DRAFT",
                  "JobCancelPlan", "JOB_CANCEL_PLAN",
                  "MonitorPollPlan", "MONITOR_POLL_PLAN",
                  "SyncManifestBuilder", "SYNC_MANIFEST_DRAFT",
                  "SmearingLadderPlan", "SMEARING_LADDER_PLAN",
                  "CutoffLadderPlan", "CUTOFF_LADDER_PLAN",
                  "ArrayJobPlan", "ARRAY_JOB_PLAN",
                  "ContainerProfileSpec", "CONTAINER_PROFILE_DRAFT",
                  "JobStateGuard", "JOB_STATE_GUARD",
                  "PhononGridLadderPlan", "PHONON_GRID_PLAN",
                  "ResubmitAdvice", "CHECKPOINT_RESUBMIT_PLAN",
                  "JobQueueAudit", "JOB_QUEUE_AUDIT",
                  "WorkflowAudit", "WORKFLOW_EXPORT_AUDIT",
                  "NebPathAudit", "NEB_PATH_AUDIT",
                  "FinalGeometryTransaction", "FINAL_GEOMETRY_APPLY",
                  "SchedulerAdapters", "SCHEDULER_ADAPTER_AUDIT",
                  "RemoteJobMonitor", "JOB_MONITOR_AUDIT",
                  "SelectiveResultSync", "SYNC_RUNTIME_AUDIT",
                  "ArraySweepPlanner", "ARRAY_JOB_AUDIT",
                  "JournalReplayMath", "replay_combined_det"]:
        if token not in service:
            error(f"ResultAnalysisService is not bound to {token}")
    for rel in ["quantumforge/com/math/SymmetricEigen3.java",
                "quantumforge/builder/QEConstraintSpec.java",
                "quantumforge/run/parser/PhonopyForceSetsReader.java",
                "quantumforge/run/parser/TrajectoryIndexReader.java",
                "quantumforge/neural/ExtXyzDatasetValidator.java",
                "quantumforge/run/parser/EnergySeriesComparer.java",
                "quantumforge/run/parser/PhononFrameSynthesis.java",
                "quantumforge/input/QEKeywordHelp.java",
                "quantumforge/hpc/ArraySweepPlanner.java",
                "quantumforge/hpc/ArrayDeckTemplate.java",
                "quantumforge/hpc/ArrayTaskIntent.java",
                "quantumforge/hpc/ArraySubmitPlan.java",
                "quantumforge/hpc/ArraySubmitSpec.java",
                "quantumforge/ssh/ArraySubmitExecutor.java",
                "quantumforge/ssh/ArrayLoopSubmitExecutor.java",
                "quantumforge/ssh/SSHServerScheduler.java",
                "quantumforge/ssh/SSHConnectRetry.java",
                "quantumforge/ssh/TransferChunkPlan.java",
                "quantumforge/app/project/viewer/run/ArraySubmitAction.java",
                "quantumforge/builder/ExtXyzCellExporter.java",
                "quantumforge/run/parser/TrajectoryWindowReader.java",
                "quantumforge/builder/SupercellMatrixValidator.java",
                "quantumforge/input/QEHubbardPlanner.java",
                "quantumforge/run/parser/QETimingParser.java",
                "quantumforge/project/WorkspaceLightIndex.java",
                "quantumforge/input/QEWorkflowTemplateLibrary.java",
                "quantumforge/builder/PoscarStructureReader.java",
                "quantumforge/export/ELateTensorDraft.java",
                "quantumforge/input/QEEsmAuditor.java",
                "quantumforge/builder/MoireTwistMath.java",
                "quantumforge/builder/PdbStructureReader.java",
                "quantumforge/builder/LammpsDataReader.java",
                "quantumforge/input/CpInputPlanner.java",
                "quantumforge/input/Wannier90WinPlanner.java",
                "quantumforge/builder/CslSigmaMath.java",
                "quantumforge/input/QEVersionRuleCatalog.java",
                "quantumforge/hpc/PoolDivisorMath.java",
                "quantumforge/com/math/QEUnits.java",
                "quantumforge/run/QEErrorSignatureCatalog.java",
                "quantumforge/input/XspectraInputPlanner.java",
                "quantumforge/input/GipawInputPlanner.java",
                "quantumforge/builder/SlabMillerMath.java",
                "quantumforge/builder/CifStructureReader.java",
                "quantumforge/builder/SdfStructureReader.java",
                "quantumforge/input/TurboLanczosInputPlanner.java",
                "quantumforge/neural/CompositionalBaselineMath.java",
                "quantumforge/run/parser/SeriesAlignmentMath.java",
                "quantumforge/run/parser/BandsFermiReviewMath.java",
                "quantumforge/run/parser/BandGapBandMath.java",
                "quantumforge/builder/TransformJournal.java",
                "quantumforge/hpc/JobDbSchema.java",
                "quantumforge/remote/OptimadeQueryBuilder.java",
                "quantumforge/run/parser/OccupationLevelsParser.java",
                "quantumforge/remote/MpApiQueryBuilder.java",
                "quantumforge/remote/SshTargetSpec.java",
                "quantumforge/remote/SftpTransferPlan.java",
                "quantumforge/remote/OptimadeStructuresParser.java",
                "quantumforge/remote/MpSummaryParser.java",
                "quantumforge/remote/SlurmScriptBuilder.java",
                "quantumforge/run/KMeshConvergenceLadder.java",
                "quantumforge/remote/SiteProfileSpec.java",
                "quantumforge/input/NebInputPlanner.java",
                "quantumforge/remote/JobCancelPlan.java",
                "quantumforge/remote/MonitorPollPlan.java",
                "quantumforge/remote/SyncManifestBuilder.java",
                "quantumforge/run/SmearingLadderPlan.java",
                "quantumforge/run/CutoffLadderPlan.java",
                "quantumforge/remote/ArrayJobPlan.java",
                "quantumforge/remote/ContainerProfileSpec.java",
                "quantumforge/remote/ContainerLaunchBridge.java",
                "quantumforge/remote/ContainerImageAttestor.java",
                "quantumforge/remote/JobStateGuard.java",
                "quantumforge/run/PhononGridLadderPlan.java",
                "quantumforge/run/ResubmitAdvice.java",
                "quantumforge/hpc/JobQueueAudit.java",
                "quantumforge/run/WorkflowAudit.java",
                "quantumforge/input/NebPathAudit.java",
                "quantumforge/run/parser/FinalGeometryTransaction.java",
                "quantumforge/hpc/PjmSchedulerAdapter.java",
                "quantumforge/hpc/SchedulerAdapters.java",
                "quantumforge/builder/JournalReplayMath.java"]:
        text = (SRC / rel).read_text(encoding="utf-8")
        if "class " not in text:
            error(f"{rel} does not declare a type")
    rel = "quantumforge/export/MethodsTextBuilder.java"
    text = (SRC / rel).read_text(encoding="utf-8")
    if "class " not in text:
        error(f"{rel} does not declare a type")
    for rel in ["quantumforge/neural/MlModelManifest.java",
                "quantumforge/neural/MLPotentialService.java"]:
        text = (SRC / rel).read_text(encoding="utf-8")
        if "class " not in text:
            error(f"{rel} does not declare a type")
    for stale in ["GNNFroceField", "GNNField"]:
        # Roadmap #136: the misspelled names must not reappear in code (comments
        # and strings are stripped so the historical note in the javadoc stays).
        for path in list(SRC.rglob("*.java")) + list(TESTS.rglob("*.java")):
            raw = path.read_text(encoding="utf-8", errors="replace")
            if stale in strip_strings_and_comments(raw):
                error(f"stale pre-rename name {stale} remains in {path.relative_to(ROOT)}")
                break
    # Maintainer requirement: the name of the premium commercial reference product
    # must never appear in code, tests, docs, or packaging. The software competes on
    # capability and scientific honesty, never on another product's brand.
    forbidden_brand = "Nano" + "Labo"
    brand_paths = [p for p in list(SRC.rglob("*.java")) + list(TESTS.rglob("*.java"))
                   + list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md"))
                   + list((ROOT / "packaging").rglob("*")) + list((ROOT / "scripts").rglob("*.py"))]
    for path in brand_paths:
        if path.is_file() and path.name != "compile_check.py":
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except (UnicodeDecodeError, OSError):
                continue
            if forbidden_brand.lower() in raw.lower():
                error(f"reference-product brand name remains in {path.relative_to(ROOT)}")
                break
    node = (SRC / "quantumforge/run/RunningNode.java").read_text(encoding="utf-8")
    if "DryRunPreflight" not in node or "ArtifactScanner" not in node or "QECommandDag" not in node:
        error("RunningNode is not wired to dry-run/DAG/artifact scanning")
    runAction = (SRC / "quantumforge/app/project/viewer/run/RunAction.java").read_text(encoding="utf-8")
    if ("postJobToServerResult" not in runAction and "RemoteSubmitChain" not in runAction) \
            or "HostKeyAcceptance" not in runAction:
        error("RunAction still uses untyped/fake SSH submit path")
    if "offerMonitoring" not in runAction or "QEFXJobMonitorDialog" not in runAction:
        error("RunAction lost the job-monitor offer wiring (batch 138)")
    if "transportHandedOff" not in runAction:
        error("RunAction lost exactly-once transport ownership tracking (batch 138)")
    if "qf-ssh-submit" not in runAction or "RemoteSubmitChain" not in runAction:
        error("RunAction lost the background submit worker / headless chain (batch 139)")
    if "SSHConnectRetry" not in runAction or "provenanceLine" not in runAction:
        error("RunAction lost the bounded connect retry with provenance (batch 145)")
    retry = SRC / "quantumforge/ssh/SSHConnectRetry.java"
    if not retry.is_file() or "isRetriable" not in retry.read_text(encoding="utf-8"):
        error("SSHConnectRetry (batch-145 retry combinator) missing its retriable owner")
    transfer = (SRC / "quantumforge/ssh/SSHFileTransfer.java").read_text(encoding="utf-8")
    if "uploadChunkedVerifiedResult" not in transfer or "TRANSFER_CHUNK_STALE" not in transfer:
        error("SSHFileTransfer lost the batch-146 chunked/resumable verified upload")
    syncRuns = (SRC / "quantumforge/ssh/SelectiveResultSync.java").read_text(encoding="utf-8")
    if "downloadVerifiedResult" not in syncRuns or "pin-verified" not in syncRuns:
        error("SelectiveResultSync lost the batch-146 hash-pinned download path")
    if "NOT hash-verified (no pins supplied)" not in syncRuns:
        error("SelectiveResultSync lost the unpinned-posture honesty sentence (batch 146)")
    svcText = (SRC / "quantumforge/run/ResultAnalysisService.java").read_text(encoding="utf-8")
    if "uploadChunkedVerifiedResult" not in svcText or "TransferChunkPlan" not in svcText:
        error("ResultAnalysisService lost the batch-146 integrity boundary/provenance")
    if "waitDialog" not in runAction or "Platform.runLater" not in runAction.replace(
            "javafx.application.Platform.runLater", "Platform.runLater"):
        error("RunAction lost its FX-marshalling/lifecycle discipline (batch 139)")
    hka = (SRC / "quantumforge/app/ssh/HostKeyAcceptance.java").read_text(encoding="utf-8")
    if "isFxApplicationThread" not in hka or "CountDownLatch" not in hka:
        error("HostKeyAcceptance lost its cross-thread audited prompt (batch 139)")
    chain = SRC / "quantumforge/ssh/RemoteSubmitChain.java"
    if not chain.is_file() or "wasTransportClosedByChain" not in chain.read_text(
            encoding="utf-8"):
        error("RemoteSubmitChain (batch 139 headless submit chain) missing ownership flags")
    monitorGui = SRC / "quantumforge/app/ssh/QEFXJobMonitorDialog.java"
    monitorModel = SRC / "quantumforge/app/ssh/MonitorLogModel.java"
    if not monitorGui.is_file() or not monitorModel.is_file():
        error("batch-138 monitor GUI host classes missing")
    else:
        monitorRaw = monitorGui.read_text(encoding="utf-8")
        if "Platform.runLater" not in monitorRaw or "shutdownNow" not in monitorRaw:
            error("QEFXJobMonitorDialog lost its FX-thread/lifecycle discipline")
        if "MAX_LINES" not in monitorModel.read_text(encoding="utf-8"):
            error("MonitorLogModel lost its owned ring bound")
    actionFx = (SRC / "quantumforge/app/project/viewer/analysis/AnalysisAction.java").read_text(
        encoding="utf-8")
    if "withContainerSiteProfile" not in actionFx:
        error("AnalysisAction lost the batch-147 launch-bridge prompt wiring")
    if "launch_bridge" not in svcText:
        error("ResultAnalysisService lost the batch-147 launch-bridge render/csv trail")
    sshJob = (SRC / "quantumforge/ssh/SSHJob.java").read_text(encoding="utf-8")
    if "SSHServerScheduler" not in sshJob:
        error("SSHJob lost the batch-144 single-owner scheduler resolution fix")
    resolver = SRC / "quantumforge/ssh/SSHServerScheduler.java"
    if not resolver.is_file() or "SSH_SCHEDULER_UNSET" not in resolver.read_text(
            encoding="utf-8"):
        error("SSHServerScheduler (batch-144 resolver) missing its typed refusals")
    loopExec = SRC / "quantumforge/ssh/ArrayLoopSubmitExecutor.java"
    if not loopExec.is_file() or "SUBMIT_LOOP_WRONG_SHAPE" not in loopExec.read_text(
            encoding="utf-8"):
        error("ArrayLoopSubmitExecutor (batch 143) missing its loop-only shape guard")
    arrayGui = SRC / "quantumforge/app/project/viewer/run/ArraySubmitAction.java"
    if not arrayGui.is_file():
        error("ArraySubmitAction (batch-144 GUI array-submit dialogue) missing")
    else:
        arrayRaw = arrayGui.read_text(encoding="utf-8")
        if "qf-array-submit" not in arrayRaw or "SSHServerScheduler" not in arrayRaw:
            error("ArraySubmitAction lost its daemon/resolver wiring (batch 144)")
        if "ArrayLoopSubmitExecutor" not in arrayRaw or "ArraySubmitExecutor" not in arrayRaw:
            error("ArraySubmitAction lost the shape-split executor wiring (batch 144)")
        if "QEFXJobMonitorDialog" not in arrayRaw or "transport.close()" not in arrayRaw:
            error("ArraySubmitAction lost the monitor offer / exactly-once closes (batch 144)")
        if "SSHConnectRetry" not in arrayRaw:
            error("ArraySubmitAction lost the bounded connect retry (batch 145)")
    viewerItems = (SRC / "quantumforge/app/project/viewer/ViewerItemSet.java").read_text(
        encoding="utf-8")
    viewerActs = (SRC / "quantumforge/app/project/viewer/ViewerActions.java").read_text(
        encoding="utf-8")
    if "Submit array sweep" not in viewerItems or "ArraySubmitAction" not in viewerActs:
        error("viewer menu lost the batch-144 array-sweep submission entry")
    sshDialog = (SRC / "quantumforge/app/ssh/QEFXSSHDialog.java").read_text(encoding="utf-8")
    sshFxml = (SRC / "quantumforge/app/ssh/QEFXSSHDialog.fxml").read_text(encoding="utf-8")
    if "schedulerCombo" not in sshDialog or "schedulerCombo" not in sshFxml:
        error("SSH dialog lost the batch-144 Job Scheduler chooser")
    neb = (SRC / "quantumforge/builder/neb/NEBPathCreator.java").read_text(encoding="utf-8")
    if "for (int k = 0; k < 3; k++)" not in neb and "for (int k = 0; k < 3; k++)" not in neb:
        # accept either classic or enhanced form
        if "for (int k = 0; k < 3; k++)" not in neb:
            if "k < 3" not in neb:
                error("NEBPathCreator lattice loop appears broken")

    
    # Batch 150: machine-mined QE namelist grammar (7.2-7.6) + audits.
    schemaDir = SRC / "quantumforge/input/schema"
    if not (schemaDir / "QENamelistSchema.java").is_file() \
            or not (schemaDir / "QESchemaData.java").is_file():
        error("batch-150 mined schema classes missing")
    else:
        schemaText = (schemaDir / "QENamelistSchema.java").read_text(encoding="utf-8")
        dataText = (schemaDir / "QESchemaData.java").read_text(encoding="utf-8")
        if "getAcceptedValuesIn" not in schemaText or "getToleratedValueDetails" not in schemaText:
            error("QENamelistSchema lost the hard/soft version-masked accessors (batch 150)")
        if "diago_ppcg_maxiter" not in dataText or "sha256" not in dataText:
            error("QESchemaData lost mined drift entries or sha256 provenance (batch 150)")
    audit = SRC / "quantumforge/input/validation/QESchemaAudit.java"
    validator = SRC / "quantumforge/input/validation/QESchemaValidator.java"
    if not audit.is_file() or "SCHEMA_VALUE_REJECTED" not in audit.read_text(encoding="utf-8"):
        error("QESchemaAudit (batch-150 pair-level core) missing its rejection codes")
    if not validator.is_file() or "validatePairs" not in validator.read_text(encoding="utf-8"):
        error("QESchemaValidator (batch-150 QEInput adapter) missing its core delegation")
    if "Mined schema audit" not in svcText:
        error("ResultAnalysisService lost the batch-150 mined-schema report section")

    # Batch 151: chunked verified download with per-chunk pins.
    transferRaw = (SRC / "quantumforge/ssh/SSHFileTransfer.java").read_text(encoding="utf-8")
    if "downloadChunkedVerifiedResult" not in transferRaw:
        error("SSHFileTransfer lost the batch-151 chunked verified download")
    if "TRANSFER_PART_MISMATCH" not in transferRaw:
        error("SSHFileTransfer lost the batch-151 per-chunk pin mismatch verdict")

    # Batch 152: BoltzTraP2 transport tables (.trace/.condtens), Fortran grammar.
    boltz = SRC / "quantumforge/run/parser/BoltzTrap2TraceParser.java"
    if not boltz.is_file():
        error("BoltzTrap2TraceParser (batch 152) missing")
    else:
        boltzRaw = boltz.read_text(encoding="utf-8")
        if "TENSOR_OTHER" not in boltzRaw or "Fortran" not in boltzRaw:
            error("BoltzTrap2TraceParser lost the tensor-family refusal / Fortran grammar (batch 152)")
    if "BOLTZTRAP2_TRANSPORT" not in svcText or "analyzeBoltzTrap2Transport" not in svcText:
        error("ResultAnalysisService lost the batch-152 BoltzTraP2 transport wiring")

    # Batch 153: eigen solver + latent master compile defects resurrected green.
    eigen = (SRC / "quantumforge/com/math/SymmetricEigen3.java").read_text(encoding="utf-8")
    if "double[] rotation = rotate(a, p, q);" not in eigen:
        error("SymmetricEigen3 lost the batch-153 rotation/accumulate call fix")
    bz = (SRC / "quantumforge/symmetry/QEBrillouinZoneGeometry.java").read_text(encoding="utf-8")
    if "faceCentroid" not in bz:
        error("QEBrillouinZoneGeometry lost the batch-153 index-order fix (sort before faces)")
    prop = (SRC / "quantumforge/project/property/ProjectProperty.java").read_text(encoding="utf-8")
    if "public ProjectProperty()" not in prop:
        error("ProjectProperty lost the batch-153 explicit blank-context ctor")
    dynmat = (SRC / "quantumforge/run/parser/QEDynmatModesParser.java").read_text(encoding="utf-8")
    if "\\\\*+" not in dynmat and '"\\\\*+"' not in dynmat:
        error("QEDynmatModesParser lost the batch-153 decoration-line tolerance")
    wa = (SRC / "quantumforge/run/WorkflowAudit.java").read_text(encoding="utf-8")
    if "private final boolean setOptions;" not in wa:
        error("WorkflowAudit lost the batch-153 setOptions field declaration")

    # Batch 154 (QE-roadmap R3): version-windowed keyword catalog + typed
    # ph.x/hp.x deck planners + phonon-dialog GUI window list.
    catalog = SRC / "quantumforge/input/QEDeckKeywordCatalog.java"
    if not catalog.is_file():
        error("QEDeckKeywordCatalog (batch 154, R3) missing")
    else:
        catalogText = catalog.read_text(encoding="utf-8")
        if "resolveVersion" not in catalogText or "QES_VERSION" not in catalogText \
                or "promptLabel" not in catalogText:
            error("QEDeckKeywordCatalog lost the fail-closed version resolution / prompt rows (batch 154)")
    ph = SRC / "quantumforge/input/PhInputPlanner.java"
    if not ph.is_file():
        error("PhInputPlanner (batch 154, R3) missing")
    else:
        phText = ph.read_text(encoding="utf-8")
        if "PH_KEYWORD_WINDOW" not in phText or "PH_VERSION" not in phText \
                or "auditStaticEmissions" not in phText:
            error("PhInputPlanner lost the version-window refusals or the typed self-audit (batch 154)")
    hp = (SRC / "quantumforge/input/QEHubbardPlanner.java").read_text(encoding="utf-8")
    if "HP_KEYWORD_WINDOW" not in hp or "no_metq0" not in hp or "auditStaticEmissions" not in hp:
        error("QEHubbardPlanner lost the batch-154 version-typed overload / no_metq0 gating")
    phononFx = (SRC / "quantumforge/app/project/editor/input/phonon/QEFXPhononController.java").read_text(encoding="utf-8")
    if "QEDeckKeywordCatalog" not in phononFx or "refreshKeywordWindow" not in phononFx:
        error("QEFXPhononController lost the batch-154 typed grammar window (GUI slice of R3)")
    phononFxml = (SRC / "quantumforge/app/project/editor/input/phonon/QEFXPhonon.fxml").read_text(encoding="utf-8")
    if "qeVersionCombo" not in phononFxml or "keywordWindowList" not in phononFxml:
        error("QEFXPhonon.fxml lost the batch-154 version picker / keyword window list")

    # Batch 155 (QE-roadmap R1+R2): extension-deck accessor + deck-text audit +
    # user-pinned validation version picker.
    qeinp = (SRC / "quantumforge/input/QEInput.java").read_text(encoding="utf-8")
    if "listExtraNamelistKeys" not in qeinp or "NAMELIST_PRESS_AI" not in qeinp \
            or "listAllNamelistKeys" not in qeinp:
        error("QEInput lost the batch-155 R1 extension-deck accessor (FCP/RISM/WANNIER.../PRESS_AI)")
    schemaVal = (SRC / "quantumforge/input/validation/QESchemaValidator.java").read_text(encoding="utf-8")
    if "validateDeckText" not in schemaVal or "CODE_TEXT_LIMIT" not in schemaVal:
        error("QESchemaValidator lost the batch-155 deck-text extension audit or its bounded read")
    vact = (SRC / "quantumforge/app/project/viewer/ViewerActions.java").read_text(encoding="utf-8")
    # What must not regress is the BEHAVIOUR: the audit version is chosen by the
    # user from the full mined list, and cancelling audits nothing. The picker
    # used to be a raw ChoiceDialog; it now goes through the UserPrompt seam so
    # the surrounding logic is testable headless (review item C2/C3). Pinning
    # the JavaFX class name would forbid that refactor while proving nothing, so
    # the check looks for the choice itself and the cancel guard.
    # Inspect the arguments of the choose() call itself: "VERSIONS appears
    # somewhere in the file" is satisfied by the unrelated newest-version
    # lookup, so it would not notice the options being narrowed to a
    # hardcoded list.
    picker = re.search(r"prompt\.choose\((.{0,400}?)\)\s*\.orElse", vact, re.S)
    if picker is None or "QENamelistSchema.VERSIONS" not in picker.group(1):
        error("ViewerActions lost the batch-155 R2 user-pinned audit-version picker "
              "(the full mined version list must be the offered choice)")
    if "schemaVersion == null" not in vact:
        error("ViewerActions lost the batch-155 R2 cancel guard (cancel must audit nothing)")
    if "audit the input against which qe grammar window" not in vact.lower():
        error("ViewerActions lost the batch-155 R2 picker text naming the grammar window")

    # Batch 156 (QE-roadmap R6): mined thermo_pw &INPUT_THERMO grammar + audit + kind wiring.
    tpwData = SRC / "quantumforge/input/schema/QEThermoPwSchemaData.java"
    tpwSchema = SRC / "quantumforge/input/schema/QEThermoPwSchema.java"
    tpwAudit = SRC / "quantumforge/input/validation/QEThermoPwDeckAudit.java"
    if not tpwData.is_file() or not tpwSchema.is_file() or not tpwAudit.is_file():
        error("batch-156 mined thermo_pw schema/audit classes missing")
    else:
        tpwDataText = tpwData.read_text(encoding="utf-8")
        if "sha256" not in tpwDataText or "buildWhatAcceptedValues" not in tpwDataText \
                or "GENERATED by scripts/thermo_pw_schema_miner.py" not in tpwDataText:
            error("QEThermoPwSchemaData lost its generated provenance header / hard what set (batch 156)")
        tpwSchemaText = tpwSchema.read_text(encoding="utf-8")
        if "entriesGroupedUnder" not in tpwSchemaText or "groupedUnder" not in tpwSchemaText:
            error("QEThermoPwSchema lost the advisory group navigation (batch 156)")
        tpwAuditText = tpwAudit.read_text(encoding="utf-8")
        if "THERMO_WHAT_REJECTED" not in tpwAuditText or "THERMO_AGGREGATE_RULE" not in tpwAuditText \
                or "INPUT_THERMO_MARKER" not in tpwAuditText:
            error("QEThermoPwDeckAudit lost its binary-mirrored refusal codes (batch 156)")
    if "THERMO_PW_DECK_AUDIT" not in svcText or "analyzeThermoPwDeckAudit" not in svcText \
            or 'name.equals("thermo_control")' not in svcText:
        error("ResultAnalysisService lost the batch-156 thermo_pw deck-audit kind wiring")
    if "459 pw.x + 80 ph.x + 33" not in svcText:
        error("ResultAnalysisService mined-schema honesty line lost the corrected 459/80/33 counts")
    if not (ROOT / "scripts/thermo_pw_schema_miner.py").is_file():
        error("thermo_pw schema miner script missing (batch 156 provenance)")

    # Batch 157 (QE-roadmap R4): mined read_cards CARD grammar + audit + kind wiring.
    cardData = SRC / "quantumforge/input/schema/QECardSchemaData.java"
    cardSchema = SRC / "quantumforge/input/schema/QECardSchema.java"
    cardAudit = SRC / "quantumforge/input/validation/QECardAudit.java"
    if not cardData.is_file() or not cardSchema.is_file() or not cardAudit.is_file():
        error("batch-157 mined card schema/audit classes missing")
    else:
        cardDataText = cardData.read_text(encoding="utf-8")
        if "sha256" not in cardDataText or "GENERATED by scripts/qe_card_schema_miner.py" not in cardDataText \
                or "T:-ATOMIC~0x1F" not in cardDataText:
            error("QECardSchemaData lost its generated provenance header / HUBBARD chain traps (batch 157)")
        cardSchemaText = cardSchema.read_text(encoding="utf-8")
        if "firstChainMatch" not in cardSchemaText or "getWarnProg" not in cardSchemaText \
                or "lookupGrammar" not in cardSchemaText:
            error("QECardSchema lost chain-order adjudication or prog-warn split (batch 157)")
        cardAuditText = cardAudit.read_text(encoding="utf-8")
        if "CARD_REMOVED_FATAL" not in cardAuditText or "CARD_OPTION_TRAP" not in cardAuditText \
                or "KP_AUTOMATIC_MESH" not in cardAuditText or "CARD_UNKNOWN_IGNORED" not in cardAuditText:
            error("QECardAudit lost its binary-mirrored refusal codes (batch 157)")
    if "QE_CARD_AUDIT" not in svcText or "analyzeQeCardAudit" not in svcText \
            or "manual select only" not in svcText:
        error("ResultAnalysisService lost the batch-157 card-audit kind wiring")
    if not (ROOT / "scripts/qe_card_schema_miner.py").is_file():
        error("card schema miner script missing (batch 157 provenance)")

    # Batch 158 (QE-roadmap R6 slice 2): thermo_pw 7-column tag window.
    tpwSchemaText2 = tpwSchema.read_text(encoding="utf-8")
    if '"2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.1.0", "2.1.1", "master"' not in tpwSchemaText2 \
            or "presentIn" not in tpwSchemaText2 or "factsForVersion" not in tpwSchemaText2 \
            or "Integer.decode(" not in tpwSchemaText2:
        error("QEThermoPwSchema lost the batch-158 tag window / drift view / decode fix")
    tpwDataText2 = tpwData.read_text(encoding="utf-8")
    if "~0x40" not in tpwDataText2 or "2.0.0:LOGICAL:.TRUE." not in tpwDataText2 \
            or "0x70" not in tpwDataText2:
        error("QEThermoPwSchemaData lost the batch-158 masks / old_ec drift / gruneisen window")
    tpwAuditText2 = tpwAudit.read_text(encoding="utf-8")
    if "THERMO_ABSENT_AT_VERSION" not in tpwAuditText2 \
            or "THERMO_GRUNEISEN_WHAT" not in tpwAuditText2 \
            or "auditDeckText(String deckText, String version)" not in tpwAuditText2:
        error("QEThermoPwDeckAudit lost the batch-158 version-pinned adjudication")
    cardSchemaT2 = cardSchema.read_text(encoding="utf-8")
    if "Integer.decode(" not in cardSchemaT2:
        error("QECardSchema lost the 0x-prefixed mask decode batch-158 honesty repair")

    # Batch 158 (QE-roadmap R5): qexsd/XML dialect boundary for grammar audits.
    dialect = SRC / "quantumforge/input/validation/QEDeckDialect.java"
    if not dialect.is_file():
        error("batch-158 QEDeckDialect sniffer missing (R5 boundary)")
    else:
        dialectText = dialect.read_text(encoding="utf-8")
        if "looksLikeXmlDeck" not in dialectText or "DECK_XML_DIALECT" not in dialectText \
                or "*.in" not in dialectText:
            error("QEDeckDialect lost its conservative XML boundary contract (batch 158)")
    cardAuditText = cardAudit.read_text(encoding="utf-8")
    if "looksLikeXmlDeck" not in cardAuditText:
        error("QECardAudit lost the batch-158 XML boundary wiring")
    tpwAuditText3 = tpwAudit.read_text(encoding="utf-8")
    if "looksLikeXmlDeck" not in tpwAuditText3:
        error("QEThermoPwDeckAudit lost the batch-158 XML boundary wiring")
    schemaVal = SRC / "quantumforge/input/validation/QESchemaValidator.java"
    if "looksLikeXmlDeck" not in schemaVal.read_text(encoding="utf-8"):
        error("QESchemaValidator.validateDeckText lost the batch-158 XML boundary wiring")

    # Batch 159 (24 auxiliary-program grammars): mined INPUT_* grammars of the
    # 24 mandated auxiliary QE programs (21 .def + XSpectra source family),
    # the deck audit, and the manual analysis-kind wiring.
    auxData = SRC / "quantumforge/input/schema/QEAuxSchemaData.java"
    auxSchema = SRC / "quantumforge/input/schema/QEAuxSchema.java"
    auxAudit = SRC / "quantumforge/input/validation/QEAuxDeckAudit.java"
    if not auxData.is_file() or not auxSchema.is_file() or not auxAudit.is_file():
        error("batch-159 mined auxiliary-program schema/audit classes missing")
    else:
        auxDataText = auxData.read_text(encoding="utf-8")
        if "GENERATED by scripts/qe_aux_schema_miner.py" not in auxDataText \
                or "sha256" not in auxDataText or 'row("cp"' not in auxDataText \
                or "option STOP-set" not in auxDataText:
            error("QEAuxSchemaData lost its generated provenance header / rows / STOP-set (batch 159)")
        auxSchemaText = auxSchema.read_text(encoding="utf-8")
        if "programsForNamelist" not in auxSchemaText or "spectra_correction" not in auxSchemaText:
            error("QEAuxSchema lost the shared-namelist routing (batch 159)")
        auxAuditText = auxAudit.read_text(encoding="utf-8")
        if "AUX_UNKNOWN_KEYWORD" not in auxAuditText or "AUX_OPTION_STOP_SET" not in auxAuditText \
                or "AUX_ABSENT_AT_VERSION" not in auxAuditText \
                or "looksLikeXmlDeck" not in auxAuditText:
            error("QEAuxDeckAudit lost its binary-mirrored codes / XML boundary (batch 159)")
    if "QE_AUX_DECK_AUDIT" not in svcText or "analyzeQeAuxDeckAudit" not in svcText \
            or "manual select only: any .in could be an aux deck" not in svcText:
        error("ResultAnalysisService lost the batch-159 aux deck-audit kind wiring")
    if not (ROOT / "scripts/qe_aux_schema_miner.py").is_file():
        error("auxiliary schema miner script missing (batch 159 provenance)")

    # Batch 160 (QE roadmap R7 frontend slice): the version-windowed aux
    # DECK BUILDER - typed planner backend + viewer dialog + menu wiring.
    auxPlanner = SRC / "quantumforge/input/QEAuxDeckPlanner.java"
    if not auxPlanner.is_file():
        error("batch-160 QEAuxDeckPlanner missing")
    else:
        auxPlannerText = auxPlanner.read_text(encoding="utf-8")
        if "QEAUX_PROGRAM" not in auxPlannerText or "QEAUX_KEYWORD_VERSION" not in auxPlannerText \
                or "renderDraft" not in auxPlannerText or "auditDraft" not in auxPlannerText \
                or "QEAuxDeckAudit" not in auxPlannerText:
            error("QEAuxDeckPlanner lost its fail-closed codes / render-audit delegation (batch 160)")
    auxDialog = SRC / "quantumforge/app/project/viewer/auxdeck/QEFXAuxDeckDialog.java"
    if not auxDialog.is_file():
        error("batch-160 QEFXAuxDeckDialog missing")
    else:
        auxDialogText = auxDialog.read_text(encoding="utf-8")
        if "QEAuxDeckPlanner" not in auxDialogText or "programCombo" not in auxDialogText \
                or "auditArea" not in auxDialogText or "Use deck text" not in auxDialogText:
            error("QEFXAuxDeckDialog lost the planner-bound builder surface (batch 160)")
    itemSetText = (SRC / "quantumforge/app/project/viewer/ViewerItemSet.java").read_text(encoding="utf-8")
    if "getAuxDeckItem" not in itemSetText or "Auxiliary deck builder ..." not in itemSetText:
        error("ViewerItemSet lost the batch-160 aux deck builder menu item")
    vactText2 = (SRC / "quantumforge/app/project/viewer/ViewerActions.java").read_text(encoding="utf-8")
    if "actionAuxDeckBuilder" not in vactText2 or "QEFXAuxDeckDialog" not in vactText2 \
            or "getAuxDeckItem" not in vactText2:
        error("ViewerActions lost the batch-160 aux deck builder action wiring")
    if not (ROOT / "tests/java/quantumforge/input/QEAuxDeckPlannerTest.java").is_file():
        error("batch-160 planner test missing")

    # Batch 161 (Roadmap #125 viewer slice): tensor directional-surface
    # headless data layer + viewer panel + menu wiring.
    sampler = SRC / "quantumforge/com/math/TensorSurfaceSampler.java"
    if not sampler.is_file():
        error("batch-161 TensorSurfaceSampler missing (#125 viewer data layer)")
    else:
        samplerText = sampler.read_text(encoding="utf-8")
        if "parseMatrix3x3" not in samplerText or "sampleSphere" not in samplerText \
                or "samplePlane" not in samplerText or "CartesianPlane" not in samplerText:
            error("TensorSurfaceSampler lost the parse contract / sphere / plane sampling (batch 161)")
    tensorDialog = SRC / "quantumforge/app/project/viewer/tensor/QEFXTensorSurfaceDialog.java"
    if not tensorDialog.is_file():
        error("batch-161 QEFXTensorSurfaceDialog missing")
    else:
        tensorDialogText = tensorDialog.read_text(encoding="utf-8")
        if "TensorSurfaceSampler" not in tensorDialogText or "sampleSphere" not in tensorDialogText \
                or "viewCombo" not in tensorDialogText or "assertBounds" not in tensorDialogText:
            error("QEFXTensorSurfaceDialog lost the sampler-bound render surface (batch 161)")
    if "getTensorSurfaceItem" not in itemSetText or "Tensor surface viewer ..." not in itemSetText:
        error("ViewerItemSet lost the batch-161 tensor surface viewer menu item")
    if "actionTensorSurfaceViewer" not in vactText2 or "QEFXTensorSurfaceDialog" not in vactText2:
        error("ViewerActions lost the batch-161 tensor surface viewer action wiring")
    if not (ROOT / "tests/java/quantumforge/com/math/TensorSurfaceSamplerTest.java").is_file():
        error("batch-161 sampler test missing")

    # Batch 162 (Roadmap #109 chart slice): BoltzTraP2 transport chart panel
    # - headless series slicer + chart geometry + viewer dialog + menu wiring.
    slicer = SRC / "quantumforge/run/parser/BoltzTrap2SeriesSlicer.java"
    if not slicer.is_file():
        error("batch-162 BoltzTrap2SeriesSlicer missing (#109 chart data layer)")
    else:
        slicerText = slicer.read_text(encoding="utf-8")
        if "distinctMuRy" not in slicerText or "TemperatureSeries" not in slicerText \
                or "SEEBECK_ZZ" not in slicerText or "isotropic-average approximation" not in slicerText:
            error("BoltzTrap2SeriesSlicer lost the mu-slice / series kinds / PF honesty (batch 162)")
    chartGeom = SRC / "quantumforge/com/math/ChartGeometry.java"
    if not chartGeom.is_file():
        error("batch-162 ChartGeometry missing")
    else:
        chartGeomText = chartGeom.read_text(encoding="utf-8")
        if "mapLinear" not in chartGeomText or "niceTicks" not in chartGeomText \
                or "padded" not in chartGeomText:
            error("ChartGeometry lost the mapping / ticks / padding helpers (batch 162)")
    transportDialog = SRC / "quantumforge/app/project/viewer/transport/QEFXTransportChartDialog.java"
    if not transportDialog.is_file():
        error("batch-162 QEFXTransportChartDialog missing")
    else:
        transportDialogText = transportDialog.read_text(encoding="utf-8")
        if "BoltzTrap2SeriesSlicer" not in transportDialogText \
                or "BoltzTrap2TraceParser" not in transportDialogText \
                or "ChartGeometry" not in transportDialogText \
                or "normalized" not in transportDialogText:
            error("QEFXTransportChartDialog lost the slicer/parser/geometry binding (batch 162)")
    if "getTransportChartItem" not in itemSetText or "Transport chart viewer ..." not in itemSetText:
        error("ViewerItemSet lost the batch-162 transport chart viewer menu item")
    if "actionTransportChartViewer" not in vactText2 or "QEFXTransportChartDialog" not in vactText2:
        error("ViewerActions lost the batch-162 transport chart viewer action wiring")
    if not (ROOT / "tests/java/quantumforge/run/parser/BoltzTrap2SeriesSlicerTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/com/math/ChartGeometryTest.java").is_file():
        error("batch-162 slicer/geometry tests missing")

    # Batch 163 (packaging execution proof): the shipped install/update/uninstall
    # scripts and the launcher obtained an executed end-to-end smoke test; three
    # real defects found by it are pinned so they can never regress silently.
    smokeSh = ROOT / "packaging/tests/smoke-portable.sh"
    if not smokeSh.is_file():
        error("batch-163 packaging smoke test missing")
    else:
        smokeText = smokeSh.read_text(encoding="utf-8")
        for needle in ("QF_SMOKE_JDK", "QF_SMOKE_JAVAFX_DIR", "QF_GUI_PLACEHOLDER_ARGS",
                       "prism.order=sw", "QUANTUMFORGE_UPDATE_API_BASE", "SMOKE RESULT",
                       "SHA-256 verification FAILED", "Unsafe path in release archive"):
            if needle not in smokeText:
                error(f"packaging smoke test lost a pinned behaviour: {needle} (batch 163)")
    smokeReadme = ROOT / "packaging/tests/README.md"
    if not smokeReadme.is_file() or "Honesty boundaries" not in smokeReadme.read_text(encoding="utf-8"):
        error("batch-163 packaging smoke README with honesty boundaries missing")
    launcherText = (ROOT / "packaging/unix/quantumforge").read_text(encoding="utf-8")
    if "LAUNCHER_SOURCE" not in launcherText or "readlink" not in launcherText:
        error("launcher lost the command-symlink resolution (batch 163: APP_HOME misderived through ~/.local/bin)")
    if "package manager" not in launcherText or "management/" not in launcherText:
        error("launcher lost the native-layout --update/--uninstall guidance (batch 163)")
    installText = (ROOT / "packaging/unix/install.sh").read_text(encoding="utf-8")
    if "mv -fT" not in installText or "symlink to a DIRECTORY" not in installText:
        error("install.sh lost the mv -T activation fix (batch 163: updates installed but never activated)")
    if "Activation failed: current pointer did not switch" not in installText:
        error("install.sh lost the fail-closed activation self-check (batch 163)")
    if 'Exec="$BIN_DIR/quantumforge"' not in installText:
        error("install.sh lost the quoted desktop Exec path (batch 163)")
    updateText = (ROOT / "packaging/unix/update.sh").read_text(encoding="utf-8")
    if "QUANTUMFORGE_UPDATE_API_BASE" not in updateText or "CURL_PROTOCOLS" not in updateText:
        error("update.sh lost the HTTPS-only mirror override plumbing (batch 163)")
    if "Install first" not in updateText or "does not look like an installer-managed" not in updateText:
        error("update.sh lost the downloaded-copy / foreign-tree refusals (batch 163)")
    for scriptName in ("packaging/unix/update.sh", "packaging/unix/uninstall.sh"):
        if "read -r answer || answer=''" not in (ROOT / scriptName).read_text(encoding="utf-8"):
            error(f"{scriptName} lost the EOF-safe confirmation read (batch 163)")
    tutorialText = (ROOT / "docs/TUTORIAL_INSTALL.md").read_text(encoding="utf-8")
    if "smoke-portable.sh" not in tutorialText or "QUANTUMFORGE_UPDATE_API_BASE" not in tutorialText:
        error("TUTORIAL_INSTALL lost the packaging smoke / mirror override documentation (batch 163)")

    # Batch 164 (Roadmap #135 pack arc): RO-Crate payload packer - staged copy +
    # post-copy re-hash against the draft pins + atomic rename activation, an
    # explicit-only licence/author metadata policy, one JSON owner shared by
    # draft and packer, and the consent-gated viewer dialog.
    packer = SRC / "quantumforge/export/RoCratePacker.java"
    if not packer.is_file():
        error("batch-164 RoCratePacker missing (#135 pack layer)")
    else:
        packerText = packer.read_text(encoding="utf-8")
        for needle in ("ROCRATE_EMPTY", "ROCRATE_TARGET", "ROCRATE_VERIFY", "ROCRATE_ACTIVATE",
                       "Source drift detected", "Nothing was activated", "METADATA_FILE",
                       "PackSummary"):
            if needle not in packerText:
                error(f"RoCratePacker lost a pinned verdict: {needle} (batch 164)")
    exporterText = (SRC / "quantumforge/export/RoCrateExporter.java").read_text(encoding="utf-8")
    if "CrateAuthor" not in exporterText or "composeJson" not in exporterText \
            or "getProjectName" not in exporterText:
        error("RoCrateExporter lost the shared composer / author record / draft name (batch 164)")
    rasText = (SRC / "quantumforge/run/ResultAnalysisService.java").read_text(encoding="utf-8")
    if "collectRoCrateCandidates" not in rasText or "Pack RO-Crate folder ..." not in rasText:
        error("ResultAnalysisService lost the single artifact-set owner / pack pointer (batch 164)")
    packDialog = SRC / "quantumforge/app/project/viewer/rocrate/QEFXRoCratePackDialog.java"
    if not packDialog.is_file():
        error("batch-164 QEFXRoCratePackDialog missing")
    else:
        packDialogText = packDialog.read_text(encoding="utf-8")
        if "PackRequest" not in packDialogText or "Pack crate" not in packDialogText \
                or "RoCratePacker" not in packDialogText:
            error("QEFXRoCratePackDialog lost the consent surface (batch 164)")
    if "getRoCratePackItem" not in itemSetText or "Pack RO-Crate folder ..." not in itemSetText:
        error("ViewerItemSet lost the batch-164 RO-Crate pack menu item")
    if "actionRoCratePack" not in vactText2 or "QEFXRoCratePackDialog" not in vactText2 \
            or "collectRoCrateCandidates" not in vactText2:
        error("ViewerActions lost the batch-164 RO-Crate pack action wiring")
    if not (ROOT / "tests/java/quantumforge/export/RoCratePackerTest.java").is_file():
        error("batch-164 packer test missing")

    # Batch 165 (thermo_pw doc triple + live graphics): thermo_pw doc-grounded
    # series parser + run scanner + live monitor dialog. Rows/units pinned to
    # the upstream example04/05/09 references at commit b73edd6.
    tpwParser = SRC / "quantumforge/run/parser/QEThermoPwSeriesParser.java"
    if not tpwParser.is_file():
        error("batch-165 QEThermoPwSeriesParser missing (thermo_pw series grammar)")
    else:
        tpwParserText = tpwParser.read_text(encoding="utf-8")
        for needle in ("EV_CURVE", "MUR_FIT", "THERMO_HARMONIC", "ANHARM_THERM",
                       "ANHARM_MAIN", "ANHARM_BULK", "ANHARM_HEAT", "ANHARM_GAMMA",
                       "THERMOPW_HEADER", "THERMOPW_CORRUPT", "getPartialTailRows",
                       "cross-pinned"):
            if needle not in tpwParserText:
                error(f"QEThermoPwSeriesParser lost a pinned grammar element: {needle} (batch 165)")
    tpwScanner = SRC / "quantumforge/run/parser/QEThermoPwRunScanner.java"
    if not tpwScanner.is_file():
        error("batch-165 QEThermoPwRunScanner missing (run-directory census)")
    else:
        tpwScannerText = tpwScanner.read_text(encoding="utf-8")
        if "no task total is fabricated" not in tpwScannerText \
                or "getExplicitNgeoProduct" not in tpwScannerText \
                or "signature" not in tpwScannerText or "uninterpreted" not in tpwScannerText:
            error("QEThermoPwRunScanner lost the honest census (batch 165)")
    tpwDialog = SRC / "quantumforge/app/project/viewer/thermopw/QEFXThermoPwLiveDialog.java"
    if not tpwDialog.is_file():
        error("batch-165 QEFXThermoPwLiveDialog missing (live monitor)")
    else:
        tpwDialogText = tpwDialog.read_text(encoding="utf-8")
        if "Timeline" not in tpwDialogText or "pollLive" not in tpwDialogText \
                or "partial write row" not in tpwDialogText or "signature" not in tpwDialogText:
            error("QEFXThermoPwLiveDialog lost the live-polling contract (batch 165)")
    if "getThermoPwLiveItem" not in itemSetText or "thermo_pw live monitor ..." not in itemSetText:
        error("ViewerItemSet lost the batch-165 thermo_pw live menu item")
    if "actionThermoPwLive" not in vactText2 or "QEFXThermoPwLiveDialog" not in vactText2:
        error("ViewerActions lost the batch-165 thermo_pw live action wiring")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEThermoPwSeriesParserTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEThermoPwRunScannerTest.java").is_file():
        error("batch-165 parser/scanner tests missing")

    # --- batch 166: thermo_pw anhar-family closure + stdout EOS extracts + run-summary kind ---
    tpwSeries = SRC / "quantumforge/run/parser/QEThermoPwSeriesParser.java"
    tpwSeriesText = tpwSeries.read_text(encoding="utf-8")
    for needle in ("ANHARM_DBULK", "ANHARM_AUX_GRUN", "ANHARM_GAMMA_GRUN",
                   "PGRUN_GAMMA", "PGRUN_FREQ",
                   'matches("output_pgrun', "dB/dp (T)",
                   "gamma is the average gruneisen parameter",
                   "output_grun.dat_freq stay unmapped on purpose"):
        if needle not in tpwSeriesText:
            error("QEThermoPwSeriesParser lost the batch-166 anhar/pgrun kinds: " + needle)
    tpwScannerText166 = (SRC / "quantumforge/run/parser/QEThermoPwRunScanner.java").read_text(encoding="utf-8")
    for needle in ("StdoutSummary", "MAX_STDOUT_BYTES", "The equilibrium lattice constant is",
                   "The total energy at the minimum is:", "unit-cell volume",
                   "getEosLineCount", "getSuffixTag", "output_pgrun", "EOS block"):
        if needle not in tpwScannerText166:
            error("QEThermoPwRunScanner lost the batch-166 stdout/suffix census: " + needle)
    if "THERMO_PW_RUN_SUMMARY" not in rasText \
            or "analyzeThermoPwRunSummary" not in rasText \
            or "QEThermoPwRunScanner.scan" not in rasText:
        error("ResultAnalysisService lost the batch-166 THERMO_PW_RUN_SUMMARY kind")
    tpwDialogText166 = (SRC / "quantumforge/app/project/viewer/thermopw/QEFXThermoPwLiveDialog.java").read_text(encoding="utf-8")
    if "renderEosCard" not in tpwDialogText166 or "eosLabel" not in tpwDialogText166 \
            or "plot-tag" not in tpwDialogText166:
        error("QEFXThermoPwLiveDialog lost the batch-166 EOS summary card / plot-tag rows")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEThermoPwSeriesParserTest.java").is_file():
        error("batch-166 parser/scanner/stdout tests missing")

    # --- batch 167: ELATE integration + thermo_pw elastic channel ---
    elateText = (SRC / "quantumforge/run/parser/QEElateAnalyzer.java").read_text(encoding="utf-8")
    for needle in ("ELATE_SHAPE", "ELATE_ASYMMETRIC", "ELATE_SINGULAR",
                   "0627e636a7c97e8678f71aea44d0851455650d3a",
                   "GRID_2D = 25", "GRID_3D = 10", "ASYMMETRY_TOLERANCE",
                   "No further analysis will be performed",
                   "polarYoung", "polarShearBand", "youngGpa", "KBAR_TO_GPA"):
        if needle not in elateText:
            error("QEElateAnalyzer lost the batch-167 ELATE mirror: " + needle)
    tpwElasticText = (SRC / "quantumforge/run/parser/QEThermoPwElasticParser.java").read_text(encoding="utf-8")
    for needle in ("THERMOPW_ELASTIC_INPUT", "THERMOPW_ELASTIC_SHAPE",
                   "THERMOPW_ELASTIC_PARTIAL", "THERMOPW_ELASTIC_HEADER",
                   "output_el_cons", "Elastic constants C_ij",
                   "toElateMatrixText", "getSoundTokens", "getDebyeTokens"):
        if needle not in tpwElasticText:
            error("QEThermoPwElasticParser lost the batch-167 elastic channels: " + needle)
    elateDialogText = (SRC / "quantumforge/app/project/viewer/elate/QEFXElateDialog.java").read_text(encoding="utf-8")
    for needle in ("Paste 6x6 stiffness matrix", "output_el_cons.dat[.gN]",
                   "polarYoung", "polarPoissonBand", "BAND_CHI_STEPS",
                   "convention difference", "No further analysis"):
        if needle not in elateDialogText:
            error("QEFXElateDialog lost the batch-167 ELATE viewer: " + needle)
    if "getElateItem" not in itemSetText or "ELATE elastic tensor analysis ..." not in itemSetText:
        error("ViewerItemSet lost the batch-167 ELATE menu item")
    if "actionElate" not in vactText2 or "QEFXElateDialog" not in vactText2:
        error("ViewerActions lost the batch-167 ELATE action wiring")
    if "ELATE_TENSOR_ANALYSIS" not in rasText \
            or "analyzeElateTensor" not in rasText \
            or "QEElateAnalyzer.analyze" not in rasText:
        error("ResultAnalysisService lost the batch-167 ELATE_TENSOR_ANALYSIS kind")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEElateAnalyzerTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEThermoPwElasticParserTest.java").is_file():
        error("batch-167 ELATE/elastic-channel tests missing")

    # --- batch 168: phonopy integration (band/dos/thermal parsers + plan builder + live studio) ---
    phBandText = (SRC / "quantumforge/run/parser/QEPhonopyBandYaml.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_BAND_INPUT", "PHONOPY_BAND_HEADER", "PHONOPY_BAND_PARTIAL",
                   "PHONOPY_BAND_SHAPE", "PHONOPY_BAND_OK",
                   "segment_nqpoint", "distance-reset",
                   "3a3e0f099da5de2556e75d72ea89b3bb22c8e97e",
                   "describe(BandYaml", "group_velocity"):
        if needle not in phBandText:
            error("QEPhonopyBandYaml lost the batch-168 band.yaml grammar: " + needle)
    phDosText = (SRC / "quantumforge/run/parser/QEPhonopyDos.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_DOS_INPUT", "PHONOPY_DOS_EMPTY", "PHONOPY_DOS_PARTIAL",
                   "PHONOPY_DOS_SHAPE", "PHONOPY_DOS_OK",
                   "# Sigma", "seriesLabels", "partialTail", "peakSummary"):
        if needle not in phDosText:
            error("QEPhonopyDos lost the batch-168 dos grammar: " + needle)
    phTpText = (SRC / "quantumforge/run/parser/QEPhonopyThermalYaml.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_TPROP_INPUT", "PHONOPY_TPROP_HEADER", "PHONOPY_TPROP_PARTIAL",
                   "PHONOPY_TPROP_SHAPE", "PHONOPY_TPROP_OK",
                   "thermal_properties:", "unit:", "primitive cell",
                   "zero_point_energy"):
        if needle not in phTpText:
            error("QEPhonopyThermalYaml lost the batch-168 thermal grammar: " + needle)
    phPlanText = (SRC / "quantumforge/run/parser/QEPhonopyPlan.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_PLAN_INPUT", "BAND_CONNECTION",
                   "phonopy-init --qe -d", "phonopy-load --band",
                   "cubicBccPreset", "FORCE_SETS", "band.conf"):
        if needle not in phPlanText:
            error("QEPhonopyPlan lost the batch-168 plan builder: " + needle)
    phDialogText = (SRC / "quantumforge/app/project/viewer/phonopy/QEFXPhonopyDialog.java").read_text(encoding="utf-8")
    for needle in ("WATCH run (live)", "BUILD conf + commands", "phonopy-load",
                   "band.yaml", "thermal_properties.yaml"):
        if needle not in phDialogText:
            error("QEFXPhonopyDialog lost the batch-168 phonopy studio: " + needle)
    if "getPhonopyItem" not in itemSetText or "Phonopy band/DOS studio ..." not in itemSetText:
        error("ViewerItemSet lost the batch-168 phonopy menu item")
    if "actionPhonopy" not in vactText2 or "QEFXPhonopyDialog" not in vactText2:
        error("ViewerActions lost the batch-168 phonopy action wiring")
    if "PHONOPY_OUTPUT" not in rasText \
            or "analyzePhonopyOutput" not in rasText \
            or "QEPhonopyBandYaml.parse" not in rasText:
        error("ResultAnalysisService lost the batch-168 PHONOPY_OUTPUT kind")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyBandYamlTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyDosTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyThermalYamlTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyPlanTest.java").is_file():
        error("batch-168 phonopy tests missing")

    # --- batch 169: phonopy NAC closure (BORN + ph.x extraction + FORCE_CONSTANTS) ---
    phBornText = (SRC / "quantumforge/run/parser/QEPhonopyBorn.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_BORN_INPUT", "PHONOPY_BORN_HEADER", "PHONOPY_BORN_EMPTY",
                   "PHONOPY_BORN_SHAPE", "PHONOPY_BORN_OK",
                   "default value", "symmetry-independent atoms", "bornText",
                   "3a3e0f099da5de2556e75d72ea89b3bb22c8e97e"):
        if needle not in phBornText:
            error("QEPhonopyBorn lost the batch-169 BORN grammar: " + needle)
    phQeBornText = (SRC / "quantumforge/run/parser/QEPhonopyQeBorn.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_QEBORN_INPUT", "PHONOPY_QEBORN_NATOM",
                   "PHONOPY_QEBORN_HEADER", "PHONOPY_QEBORN_SHAPE", "PHONOPY_QEBORN_OK",
                   "Dielectric constant in cartesian axis", "without acoustic",
                   "LAST-BLOCK-WINS", "parse_ph_out", "symmetrize_tensors"):
        if needle not in phQeBornText:
            error("QEPhonopyQeBorn lost the batch-169 ph.x extraction grammar: " + needle)
    phFcText = (SRC / "quantumforge/run/parser/QEPhonopyForceConstants.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_FC_INPUT", "PHONOPY_FC_EMPTY", "PHONOPY_FC_PARTIAL",
                   "PHONOPY_FC_SHAPE", "PHONOPY_FC_OK",
                   "%4d %4d", "check_force_constants_indices", "p2s_map",
                   "MAX_CELLS", "describe("):
        if needle not in phFcText:
            error("QEPhonopyForceConstants lost the batch-169 FC grammar: " + needle)
    phPlanText169 = (SRC / "quantumforge/run/parser/QEPhonopyPlan.java").read_text(encoding="utf-8")
    for needle in ("NAC = .TRUE.", "phonopy-qe-born", "--nonac",
                   "removed in phonopy v4", "epsil = .true.",
                   "public Request nac(boolean enable)"):
        if needle not in phPlanText169:
            error("QEPhonopyPlan lost the batch-169 NAC extension: " + needle)
    phDialogText169 = (SRC / "quantumforge/app/project/viewer/phonopy/QEFXPhonopyDialog.java").read_text(encoding="utf-8")
    for needle in ("Extract BORN from a ph.x output", "NAC (BORN file: LO-TO correction)",
                   "saveBorn", "drawForceConstants", "drawTextCard",
                   "currentQeBorn", "FORCE_CONSTANTS", "bornPreview"):
        if needle not in phDialogText169:
            error("QEFXPhonopyDialog lost the batch-169 NAC/FC studio: " + needle)
    if "QEPhonopyBorn.parse" not in rasText \
            or "QEPhonopyForceConstants.parse" not in rasText \
            or "phonopy,born_charge_tensors" not in rasText \
            or "phonopy,fc_blocks_parsed" not in rasText:
        error("ResultAnalysisService lost the batch-169 BORN/FORCE_CONSTANTS routing")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyBornTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyQeBornTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyForceConstantsTest.java").is_file():
        error("batch-169 BORN/qe-born/FORCE_CONSTANTS tests missing")

    # --- batch 170: phonopy-gruneisen mode-gamma channel (band + mesh yaml + plan) ---
    gruYamlText = (SRC / "quantumforge/run/parser/QEPhonopyGruneisenYaml.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_GRUNEISEN_INPUT", "PHONOPY_GRUNEISEN_HEADER",
                   "PHONOPY_GRUNEISEN_EMPTY", "PHONOPY_GRUNEISEN_PARTIAL",
                   "PHONOPY_GRUNEISEN_SHAPE", "PHONOPY_GRUNEISEN_OK",
                   "Mode.BAND", "Mode.MESH", "multiplicity", "-V/(2*omega^2)",
                   "readQBlock", "file name plays no part", "Gamma-point", "describe("):
        if needle not in gruYamlText:
            error("QEPhonopyGruneisenYaml lost the batch-170 gamma grammar: " + needle)
    gruPlanText = (SRC / "quantumforge/run/parser/QEPhonopyGruneisenPlan.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_GRUNEISEN_PLAN_INPUT", "PHONOPY_GRUNEISEN_PLAN_OK",
                   "phonopy-gruneisen", "--readfc", "--band=\"auto\"",
                   "deprecated at v2.44", "siBandPreset", "THREE phonon",
                   "gruneisen_mesh.yaml"):
        if needle not in gruPlanText:
            error("QEPhonopyGruneisenPlan lost the batch-170 3-volume builder: " + needle)
    phDialogText170 = (SRC / "quantumforge/app/project/viewer/phonopy/QEFXPhonopyDialog.java").read_text(encoding="utf-8")
    for needle in ("gruneisen_mesh.yaml", "drawGruneisen", "gruButton",
                   "gamma(q,nu)", "negative-gamma entries"):
        if needle not in phDialogText170:
            error("QEFXPhonopyDialog lost the batch-170 live gamma chart: " + needle)
    if "gruneisen_mesh.yaml" not in rasText \
            or "QEPhonopyGruneisenYaml.parse" not in rasText \
            or "phonopy,gruneisen_mode" not in rasText \
            or "phonopy,gruneisen_gamma_min" not in rasText:
        error("ResultAnalysisService lost the batch-170 gruneisen routing")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyGruneisenYamlTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyGruneisenPlanTest.java").is_file():
        error("batch-170 gruneisen tests missing")

    # --- batch 171: phonopy q2r.x Experimental route (PH_Q2R parser + flow plan) ---
    q2rFcText = (SRC / "quantumforge/run/parser/QEPhonopyQ2rFc.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_Q2R_INPUT", "PHONOPY_Q2R_EMPTY",
                   "PHONOPY_Q2R_HEADER", "PHONOPY_Q2R_SHAPE",
                   "PHONOPY_Q2R_PARTIAL", "PHONOPY_Q2R_OK",
                   "Ry/au^2", "xyz2 xzy1 p2 p1", "translationIndex", "toBornText",
                   "pw_forum", "describe("):
        if needle not in q2rFcText:
            error("QEPhonopyQ2rFc lost the batch-171 PH_Q2R grammar: " + needle)
    q2rPlanText = (SRC / "quantumforge/run/parser/QEPhonopyQ2rPlan.java").read_text(encoding="utf-8")
    for needle in ("PHONOPY_Q2R_PLAN_INPUT", "PHONOPY_Q2R_PLAN_OK",
                   "make_fc_q2r.py", "zasr", "epsil=.false.", "cp ",
                   "Experimental", "naclPreset", "make_born_q2r.py"):
        if needle not in q2rPlanText:
            error("QEPhonopyQ2rPlan lost the batch-171 flow builder: " + needle)
    phDialogText171 = (SRC / "quantumforge/app/project/viewer/phonopy/QEFXPhonopyDialog.java").read_text(encoding="utf-8")
    for needle in ("q2rButton", "q2rFlowButton", "drawQ2rFc",
                   "QEPhonopyQ2rFc.parse", "MAX_WATCHED_FC", "flowPreview"):
        if needle not in phDialogText171:
            error("QEFXPhonopyDialog lost the batch-171 q2r studio: " + needle)
    if "QEPhonopyQ2rFc.parse" not in rasText \
            or "phonopy,q2r_blocks_parsed" not in rasText \
            or "phonopy,q2r_nac_block" not in rasText \
            or "endsWith(\".fc\")" not in rasText:
        error("ResultAnalysisService lost the batch-171 q2r .fc routing")
    if not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyQ2rFcTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/QEPhonopyQ2rPlanTest.java").is_file():
        error("batch-171 q2r tests missing")

    # --- batch 172: BoltzTraP2Y fork integration (halltens + Yi-Wang dope channels + btp2 studio + plan) ---
    btp2TraceText = (SRC / "quantumforge/run/parser/BoltzTrap2TraceParser.java").read_text(encoding="utf-8")
    for needle in ("HALLTENS", "TRACE_DOPE_X", "TRACE_DOPE_EXT", "mu-Ef[eV]",
                   "rh27", "getRhEvenPermutationAverage", "cv_x",
                   "even-permutation", "save_halltens", "save_traceEXT",
                   "headerCertifiedDopeExt"):
        if needle not in btp2TraceText:
            error("BoltzTrap2TraceParser lost the batch-172 fork grammars: " + needle)
    btp2SlicerText = (SRC / "quantumforge/run/parser/BoltzTrap2SeriesSlicer.java").read_text(encoding="utf-8")
    for needle in ("sliceMuCurve", "MuCurve", "distinctTemperatures",
                   "DOS_EF", "N_CARRIERS", "RH_AVG", "CV_X", "S_X", "N_X",
                   "fabricating"):
        if needle not in btp2SlicerText:
            error("BoltzTrap2SeriesSlicer lost the batch-172 mu-curve/raw-column channel: " + needle)
    btp2DopeDosText = (SRC / "quantumforge/run/parser/BoltzTrap2DopeDosParser.java").read_text(encoding="utf-8")
    for needle in ("BOLTZTRAP2_DOPEDOS", "DopeDosKind", "DopeDosTable",
                   "os.rename", "_raw", "fp.write", "partialTailHeld"):
        if needle not in btp2DopeDosText:
            error("BoltzTrap2DopeDosParser lost the batch-172 dope-table grammar: " + needle)
    btp2PlanText = (SRC / "quantumforge/run/parser/BoltzTrap2Btp2Plan.java").read_text(encoding="utf-8")
    for needle in ("BOLTZTRAP2_PLAN_INPUT", "liznsbPreset", "qePreset",
                   "qes-1.0", "components_argument", "L0 = 2.44e-8",
                   "mutually-exclusive", "zero-width energy window",
                   "empty temperature specification", "parseArrayArgument",
                   "fermisurface", "ZeroDivisionError"):
        if needle not in btp2PlanText:
            error("BoltzTrap2Btp2Plan lost the batch-172 CLI mirror: " + needle)
    btp2DialogText = (SRC / "quantumforge/app/project/viewer/transport/QEFXBoltzTrap2Dialog.java").read_text(encoding="utf-8")
    for needle in ("familyOf", "watchTimer", "WATCH_POLL_SECONDS",
                   "planLiznsb", "even-permutation", "enumerated, never parsed",
                   "BoltzTrap2DopeDosParser.parse", "Hall component"):
        if needle not in btp2DialogText:
            error("QEFXBoltzTrap2Dialog lost the batch-172 studio: " + needle)
    if "getBoltzTrap2StudioItem" not in (SRC / "quantumforge/app/project/viewer/ViewerItemSet.java").read_text(encoding="utf-8") \
            or "actionBoltzTrap2Studio" not in (SRC / "quantumforge/app/project/viewer/ViewerActions.java").read_text(encoding="utf-8"):
        error("BoltzTraP2 studio launch wiring lost")
    if "analyzeBoltzTrap2Hall" not in rasText \
            or "analyzeBoltzTrap2DopeDos" not in rasText \
            or "halltens" not in rasText \
            or "ohall_m3_c" not in rasText \
            or "mu_minus_ef_ev_as_written" not in rasText:
        error("ResultAnalysisService lost the batch-172 BoltzTraP2 routing")
    if not (ROOT / "tests/java/quantumforge/run/parser/BoltzTrap2DopeDosParserTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/run/parser/BoltzTrap2Btp2PlanTest.java").is_file():
        error("batch-172 BoltzTraP2 tests missing")

    # --- batch 173: VASP input side (INCAR schema/deck/audit + KPOINTS grammar + presets + workbench) ---
    vasSchemaText = (SRC / "quantumforge/input/schema/VaspIncarSchema.java").read_text(encoding="utf-8")
    for needle in ("tierOf", "WIKI_WINDOW", "wikiUrl", "TIER2", "isRecognizedName"):
        if needle not in vasSchemaText:
            error("VaspIncarSchema lost the batch-173 tier window: " + needle)
    vasSchemaDataText = (SRC / "quantumforge/input/schema/VaspIncarSchemaData.java").read_text(encoding="utf-8")
    for needle in ("TIER1_ROWS", "10^{-4}", "AEXX", "TIER2_NAMES", "available ranks"):
        if needle not in vasSchemaDataText:
            error("VaspIncarSchemaData lost the batch-173 pinned catalogue: " + needle)
    vasDeckText = (SRC / "quantumforge/input/validation/VaspIncarDeck.java").read_text(encoding="utf-8")
    for needle in ("VASP_INCAR_EMPTY", "expandArray", "curly group", "blank(s) after",
                   "VASP_INCAR_INPUT", "occurrencesOf", "ignored"):
        if needle not in vasDeckText:
            error("VaspIncarDeck lost the batch-173 INCAR grammar: " + needle)
    vasAuditText = (SRC / "quantumforge/input/validation/VaspIncarDeckAudit.java").read_text(encoding="utf-8")
    for needle in ("VASP_NPAR_OVERRIDES_NCORE", "VASP_POTIM_REQUIRED_FOR_MD",
                   "silently ignored", "CODE_CONTINUATION",
                   "VASP_LDIPOL_NEEDS_IDIPOL", "VASP_TETRA_GAMMA_MESH",
                   "auditDeckText"):
        if needle not in vasAuditText:
            error("VaspIncarDeckAudit lost the batch-173 consistency rules: " + needle)
    vasKptText = (SRC / "quantumforge/input/validation/VaspKpointsDeck.java").read_text(encoding="utf-8")
    for needle in ("VASP_KPOINTS_SHAPE", "Tetrahedra", "ICHARG = 11",
                   "commensurate with the reciprocal lattice", "gammaMesh",
                   "bandPath", "LINE_MODE", "we recommend", "toKpointsText"):
        if needle not in vasKptText:
            error("VaspKpointsDeck lost the batch-173 KPOINTS grammar: " + needle)
    vasPresetsText = (SRC / "quantumforge/input/VaspIncarPresets.java").read_text(encoding="utf-8")
    for needle in ("KEYS", "HFSCREEN = 0.2", "commented recipe",
                   "companionMeshes", "EXAMPLE VALUE", "never executes VASP"):
        if needle not in vasPresetsText:
            error("VaspIncarPresets lost the batch-173 preset bundles: " + needle)
    if "VASP_INPUT_AUDIT" not in rasText or "analyzeVaspInputAudit" not in rasText \
            or "vasp-incar-audit" not in rasText or "vasp-kpoints" not in rasText:
        error("ResultAnalysisService lost the batch-173 VASP input audit routing")
    vasExtText = (SRC / "quantumforge/app/extension/vasp/VASPExtension.java").read_text(encoding="utf-8")
    for needle in ("VaspIncarPresets", "Audit the preview text", "copyToClipboard"):
        if needle not in vasExtText:
            error("VASPExtension lost the batch-173 workbench: " + needle)
    if not (ROOT / "tests/java/quantumforge/input/schema/VaspIncarSchemaTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/input/validation/VaspIncarDeckTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/input/validation/VaspIncarDeckAuditTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/input/validation/VaspKpointsDeckTest.java").is_file() \
            or not (ROOT / "tests/java/quantumforge/input/VaspIncarPresetsTest.java").is_file():
        error("batch-173 VASP input tests missing")

    cap = (SRC / "quantumforge/capability/CapabilityRegistry.java").read_text(encoding="utf-8")
    if "Strict known_hosts" not in cap:
        error("CapabilityRegistry SSH status not updated")
    if "spglib/seekpath sidecar protocol v2" not in cap and "spglib JSON sidecar" not in cap:
        error("CapabilityRegistry symmetry status not updated")

    if ERRORS:
        print(f"Compile-check FAILED ({len(ERRORS)}):")
        for e in ERRORS:
            print(" -", e)
        return 1
    print(f"Compile-check passed for {len(files)} Java files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
