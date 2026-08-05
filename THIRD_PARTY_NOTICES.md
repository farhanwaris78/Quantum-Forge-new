# Third-party notices

QuantumForge's repository license does not replace the licenses of upstream portions or dependencies. Release artifacts include a CycloneDX SBOM with exact resolved versions.

## Upstream heritage

The repository `LICENSE` states that portions are based on the BURAI project, copyright Satomichi Nishihara (2018), licensed under Apache License 2.0. Preserve the applicable upstream copyright, attribution, and NOTICE material when redistributing those portions. A provenance audit that maps every inherited file to its upstream commit is still required; see `docs/CODE_AUDIT.md`.

## Runtime/build dependencies

| Component | Coordinates/version used by Maven | License (upstream metadata) |
|---|---|---|
| OpenJFX | `org.openjfx:javafx-*` 17.0.19 | GPL-2.0 with Classpath Exception |
| Gson | `com.google.code.gson:gson` 2.14.0 | Apache-2.0 |
| exp4j | `net.objecthunter:exp4j` 0.4.8 | Apache-2.0 |
| JCodec | `org.jcodec:jcodec` and `jcodec-javase` 0.2.5 | BSD-style / FreeBSD |
| JSch maintained fork | `com.github.mwiede:jsch` 2.28.0 | Revised BSD, plus component notices |
| JUnit Jupiter (tests only) | `org.junit.jupiter:*` 5.13.4 | EPL-2.0 |
| Maven plugins | versions pinned in `pom.xml` | See each plugin's upstream metadata |

Authoritative license texts are distributed in the corresponding Maven artifacts and upstream repositories. Native packages created with `jpackage` include a Java runtime whose notices are available from that JDK distributor.

## External scientific programs

Quantum ESPRESSO, thermo_pw, phonopy, BoltzTraP2, XCrySDen, LAMMPS, spglib/seekpath, VASP, and CASTEP are **not bundled**. They remain governed by their own terms. In particular, VASP and CASTEP generally require separately obtained licenses; QuantumForge does not grant access to either program.

## Icons and media

Legacy source comments attribute some SVG icons to Flaticon. The repository currently lacks a per-icon provenance/license manifest. Do not assume that every historical image is redistributable until issue `P0-LEGAL-2` in the audit is resolved. Release maintainers should replace unclear assets or record author, source URL, license, and required attribution for each asset.
