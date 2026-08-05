# QuantumForge 2.0.0

QuantumForge is a JavaFX desktop application for preparing, running, and inspecting selected [Quantum ESPRESSO](https://www.quantum-espresso.org/) workflows. It includes crystal/molecular structure readers and viewers, QE namelist/card editors, local process execution, and parsers/plots for several common outputs.

> **Scientific-status warning:** this repository also contains disconnected experimental prototypes. A class name or menu label is not evidence of a complete or validated scientific workflow. Unvalidated surfaces are now hidden unless you launch with `--experimental`, and the matrix below is generated from the code's own capability registry rather than maintained by hand. Read it and the [code audit](docs/CODE_AUDIT.md) before using results in research.

## Current capability matrix

*Generated from `CapabilityRegistry`; run `quantumforge --capability-matrix`, or
`scripts/generate_capability_matrix.py` after changing the registry. CI fails if
this block is stale.*

<!-- BEGIN GENERATED CAPABILITY MATRIX -->
<!-- Generated from src/quantumforge/capability/CapabilityRegistry.java
     by scripts/generate_capability_matrix.py. Do not edit by hand:
     change the registry, then rerun the script. -->

| Area | Maturity | Status |
|---|---|---|
| Structure I/O | **Supported** | CIF/XYZ/XSF/CUBE/POSCAR readers and reviewed CIF/XYZ/POSCAR export are present. _Required next: Expand independent ASE/pymatgen round-trip fixtures._ |
| Quantum ESPRESSO input editor | **Partial** | Core pw.x SCF, relaxation, MD, bands, and DOS models/editors are present. _Required next: Complete version-aware schema and multi-version QE golden tests._ |
| Local Quantum ESPRESSO execution | **Partial** | ProcessBuilder is driven with dry-run preflight, typed command DAG stage skipping, XML-first data-file-schema parsing (energy/Fermi/force/stress/atomic forces) when present, NEB/phonon command DAGs, run manifests, restart/resubmit planning, workflow export, process-tree cancellation, live log tailing, and SCF/geometry analysis. _Required next: Add real multi-version QE golden integration tests against installed engines._ |
| SSH and HPC schedulers | **Partial** | Strict known_hosts store, JSch transport, host-key acceptance UI helper, selective result sync with checksum cache, remote job monitor with backoff, safe cancel-by-id, SLURM/PBS/SGE adapters, site profiles, durable job-queue store, and job-state records exist; live multi-cluster validation is still required. _Required next: Validate against two real clusters and polish fingerprint dialog UX._ |
| thermo_pw | **Experimental** | 18 per-what fan tabs with the full INPUT_THERMO schema and mode-scoped run-state badges; a two-tab input file (thermo_control + the QE SCF input) plus an editable ph_control for the phonon modes; correct execution (thermo_pw.x with the pw.x input on stdin); EOS fit (Murnaghan/Birch-Murnaghan, ASE-verified), OUTCAR/DOSCAR/series/grun/piezo/epsilon/B-factor/band parsers on real upstream reference fixtures; charts, runbook, images advisor, two-step workflow planner, pipeline driver, what-wizard and accuracy guards. The remaining gaps need a real thermo_pw run (real captures for the format-pinned parsers). _Required next: Capture real thermo_pw outputs (tools/capture_thermo_pw_run.sh) and swap the format-pinned fixtures; run the 25-example harness._ |
| phonopy/phono3py | **Unavailable** | A unit-explicit, validated FORCE_SETS serializer exists, but there is no displacement-job workflow. _Required next: Implement isolated Python protocol, displacement jobs, force collection, and YAML parsing._ |
| BoltzTraP2 | **Unavailable** | The btp2 command can be detected but no conversion, execution, or parser exists. _Required next: Implement dense-band conversion, interpolation diagnostics, tensors, and unit tests._ |
| XCrySDen | **Partial** | Safe temp XSF export and argument-array launch are implemented; requires a local xcrysden binary and display. _Required next: Add remote/X11 lifecycle tests and density/grid XSF export._ |
| VASP | **Experimental** | 13 per-mode INCAR tabs (relax/static/DOS/band/HSE06/TB-mBJ/optics/SLME/EOS/elastic/transport) with wiki-verified schemas, mode-scoped run-state badges, per-mode KPOINTS, INCAR audit with inline markers, OUTCAR/DOSCAR/OSZICAR parsers, sweep planners + consent-guarded array previews, POTCAR order checker, MAGMOM autofill, NBANDS helper and HSE cost estimator. POTCAR is never written (licensed dataset). _Required next: Add real VASP captures (tools/capture_vasp_run.sh) for the format-pinned parsers and end-to-end workflow tests._ |
| CASTEP | **Unavailable** | No .cell/.param model, execution adapter, or results parser exists. _Required next: Build a separately licensed plugin and private reference suite._ |
| Symmetry and band paths | **Partial** | The spglib/seekpath sidecar protocol v2 supports dataset, primitive/conventional standardization and k-path, and is now reachable from the GUI: the Band tab detects the space group from the STRUCTURE (not just ibrav) and can apply the standard high-symmetry path. Without the sidecar the space group stays undetermined and nothing is guessed. _Required next: Ship a locked sidecar environment and COD/ICSD-permitted round-trip fixtures._ |
| LAMMPS | **Experimental** | A small script skeleton exists without a data writer, runner, or parser. _Required next: Implement a unit-aware plugin and force/energy conformance fixtures._ |
| Machine-learning potentials | **Experimental** | Python package probes exist without model inference, units, uncertainty, or domain checks. _Required next: Build an isolated, locked, backend-neutral worker protocol and conformance suite._ |
| Advanced science prototypes | **Unavailable** | Topology, catalysis, battery, spectroscopy, and superconductivity sketches are not validated workflows. This also covers the structure-modeller tools (super-lattice, symmetry refinement, skyrmion/fracture/anharmonic-phonon panels) and Bader charge analysis, which previously reported success without computing anything. _Required next: Implement as reviewed plugins backed by real engines and benchmark data._ |
| Jupyter Lab upload | **Unavailable** | The menu action reported 'Upload Successful' without transferring anything; no notebook server client, transfer, or session management exists. _Required next: Implement a real notebook-server client with authentication and verified transfer._ |
| Grand-project export | **Unavailable** | The menu action reported a successful export without writing any files. _Required next: Implement the multi-project bundle format and a verified writer._ |
| Cross-platform packaging | **Partial** | Versioned portable/native installers, update/uninstall, SBOM, Ubuntu 20.04 baseline, Arch PKGBUILD, Windows/macOS scripts, and the quantumforge CLI exist. _Required next: Activate authorized cross-platform CI runners and configure Windows/macOS code signing._ |

<!-- END GENERATED CAPABILITY MATRIX -->

QuantumForge does **not** distribute Quantum ESPRESSO, pseudopotentials, VASP, CASTEP, `thermo_pw`, phonopy, BoltzTraP2, or XCrySDen. Their licenses and installation requirements apply separately.

## Install and launch

The cross-platform command that starts the GUI is:

```text
quantumforge
```

Use that same word in a local terminal **or** in MobaXterm/SSH with X11 forwarding.

Useful non-GUI commands:

```text
quantumforge --version
quantumforge --doctor
quantumforge --capabilities
quantumforge --update
quantumforge --uninstall
```

See the complete, checksum-first tutorial covering Ubuntu 20.04→current, Arch,
Windows 10/11, macOS Intel/Apple Silicon, safe update/uninstall, and remote GUI:

- **[Full multi-platform install tutorial](docs/TUTORIAL_INSTALL.md)**
- **[How to publish the first release](docs/FIRST_RELEASE.md)**
- **[Installation, update, uninstall, and MobaXterm/X11 guide](docs/INSTALLATION.md)**
- **[External scientific software setup](docs/SCIENTIFIC_SOFTWARE_GUIDE.md)**
- **[Release integrity and security model](docs/RELEASE_AND_SECURITY.md)**
- **[Deep code/scientific audit](docs/CODE_AUDIT.md)**
- **[Consolidated roadmap](docs/ROADMAP.md)**

## Build from source

Requirements: a 64-bit JDK 17+, Maven 3.9+, Git, and platform GUI libraries.

```bash
git clone https://github.com/farhanwaris78/Quantum-Forge.git
cd Quantum-Forge
mvn clean verify
mvn javafx:run
```

`mvn verify` compiles approximately 100,000 lines of Java/FXML/CSS, runs the test suite, resolves maintained dependencies, and creates `target/quantumforge-sbom.json`.

Platform artifacts are built with:

```bash
# Linux/macOS portable archive
packaging/build-portable.sh linux x64

# Linux/macOS self-contained app/native package
packaging/build-native.sh app-image   # or deb, rpm, dmg, pkg
```

```powershell
# Windows portable ZIP and self-contained package
.\packaging\build-portable.ps1 -Machine x64
.\packaging\build-native.ps1 -Type msi
```

The obsolete `bin/build.xml` and `bin/launch4j.xml` are retained only as historical files; they contain old absolute developer paths and are not the supported build.

## Troubleshooting: "CI is red but I can't see the logs"

If a GitHub Actions run fails and the logs are unreachable (expired
token, network policy), the artifact count of the latest run tells you
where it failed before you ever open a log:

```bash
RID=$(gh api "repos/OWNER/REPO/actions/runs?branch=BRANCH&per_page=1" --jq '.workflow_runs[0].id')
gh api "repos/OWNER/REPO/actions/runs/$RID/artifacts" --jq '.artifacts|length'
```

| Artifacts | Meaning |
|---|---|
| 0 | **Compile error** - the build never reached the tests. |
| 2 | Tests compiled and ran, then **failed** - an assertion is wrong (often the test's, not the code's). |
| 3 | **Green** - all jobs passed and reports uploaded. |

A green `conclusion` with fewer than 3 artifacts means something was
skipped; check before believing it. The failing test name can then be
found by bisecting (push a branch with the new tests stripped) or from
the check-run annotations:

```bash
CR=$(gh api "repos/OWNER/REPO/commits/SHA/check-runs" --jq '.check_runs[] | select(.name=="Test (Java 17)") | .id' | head -1)
gh api "repos/OWNER/REPO/check-runs/$CR/annotations" --jq '.[] | {path, start_line, message}'
```

## Research reproducibility rules

1. Record the QuantumForge version, QE version/commit, pseudopotential filenames and checksums, MPI implementation, compiler/math libraries, input files, and convergence evidence.
2. Converge cutoffs, k/q meshes, smearing, supercell dimensions, vacuum, thresholds, and finite-displacement/strain amplitudes for the property—not only total energy.
3. Inspect generated input against the official engine documentation before launching expensive jobs.
4. Validate a workflow against a reference material and, where possible, a second parser/code.
5. Never interpret a GUI default, heuristic, or prototype formula as a universal physical parameter.

## License

The repository-level terms are in [`LICENSE`](LICENSE) and are proprietary. Portions identify an Apache-2.0-licensed upstream heritage, and bundled/runtime dependencies have their own licenses; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). The older plain-text `README` contained an inconsistent Apache statement and is superseded by this file and `LICENSE`.
