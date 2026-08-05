# Packaging smoke tests

`smoke-portable.sh` is the **executed** proof that the portable packaging does
what `docs/TUTORIAL_INSTALL.md` promises. It mocks nothing that belongs to the
product: the real `install.sh`, `update.sh`, `uninstall.sh`, `verify-checksums.sh`
and the real `bin/quantumforge` launcher run inside a temporary sandbox
(temporary `HOME`, temporary XDG dir, temporary release mirror). Nothing outside
the sandbox is read, written, or left behind.

## Run it

```bash
packaging/tests/smoke-portable.sh                 # works with bash + coreutils alone
QF_SMOKE_JDK=/path/to/jdk17/bin packaging/tests/smoke-portable.sh   # full chain
```

| Environment variable  | Effect |
|---|---|
| `QF_SMOKE_JDK` | Directory containing `javac`/`java`/`jar` (JDK 17+). Enables the real-launcher chain and the loopback update section. Without it the launcher is driven by an instrumented stub `java` and the unavailable sections are skipped with explicit notes. |
| `QF_SMOKE_JAVAFX_DIR` | Directory with the real `javafx-*-<classifier>.jar` modules (e.g. `target/dependency` after `mvn verify`). Without it, **empty placeholder modules** are generated so the launcher's `--module-path` can start the JVM. |
| `QF_SMOKE_KEEP=1` | Keep the sandbox directory for forensics. |

Exit code is `0` only when every assertion in every runnable section passed.

## What is really exercised

1. **Launcher argument composition** — exact JVM argv (module path, `--add-modules`,
   classpath, main class, user args), the `-Dprism.order=sw` software-rendering
   guard for X11-forwarded sessions (`ssh -X` / MobaXterm), `QUANTUMFORGE_JAVA_OPTS`
   splitting, Java discovery precedence (`QUANTUMFORGE_JAVA_HOME` > `JAVA_HOME` >
   PATH), the missing-Java and missing-jar refusals, `--update`/`--uninstall`
   delegation to the management scripts, and the package-manager guidance when a
   native layout has no management scripts.
2. **Real JVM runs** (with `QF_SMOKE_JDK`) — the real `QuantumForgeLauncher`
   compiled from `src/` answers `--version`, `--help`, `--capabilities`,
   `--doctor` (including the honest "no DISPLAY" warning), by the bare word
   `quantumforge` resolved through PATH.
3. **Lifecycle** — install, idempotent reinstall, cancelled uninstall (deletes
   nothing), confirmed uninstall (keeps `~/.quantumforge`), interactive purge
   (deletes it), non-interactive purge (refused), foreign-directory refusal, and
   the refusal of `update.sh` when invoked inside an unpacked download.
4. **Verified update** — against a loopback mirror shaped like the GitHub
   releases API: happy-path update with rollback copy kept, already-current
   no-op, checksum-tamper abort with the running version untouched, archive
   path-traversal refusal, and the HTTPS-only posture (plain HTTP away from
   loopback is refused).
5. **Checksum verifier** — accepts a good directory, rejects tampered content.
6. **Syntax sweep** — `bash -n` over every shipped shell script.

## Honesty boundaries (what is NOT claimed)

- **GUI pixels are not tested.** No display exists in a headless runner. For the
  GUI-branch runs the jar contains a clearly marked placeholder for `QEFXMain`
  that records the forwarded argv — entry-point reachability and argument
  plumbing are proven, rendering is not. Test the GUI on a real desktop or an
  X11-forwarded session.
- **JavaFX modules may be empty placeholders** (see table above); then JavaFX
  class loading is not exercised. Provide `QF_SMOKE_JAVAFX_DIR` for full fidelity.
- The placeholder module descriptors have no `requires` edges; unlike the real
  JavaFX modules they prove only presence on the module path.
- The update mirror is loopback HTTP stub data; production updates remain
  HTTPS-only against the real releases API, which is asserted as a refusal case.
- Windows PowerShell scripts are reviewed and CI-exercised, not run by this
  POSIX script.
