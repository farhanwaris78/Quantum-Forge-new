# Changelog

## Unreleased

### A parallel task that threw hung the caller forever

`Parallel.forEach` waits on a worker counter with an **untimed** `wait()`, and
only the worker can raise it. The increment sat at the end of the worker body
rather than in a `finally`, so if the caller's `perform()` threw, that worker
died without incrementing and `forEach` blocked **permanently** on whatever
thread invoked it.

**Reachable on a real path.** `PseudoLibrary` runs this over every file in the
user's pseudopotential directory, calling `new PseudoPotential(file)` — which
reads and XML-parses an arbitrary user file. A malformed UPF, an unreadable
permission, or a directory entry that is not a file all raise from inside
`perform()`. Because `PseudoLibrary.waitToLoad()` blocks on that load, the whole
pseudopotential subsystem would wedge, not just one task.

Same shape as the `LogParser.endParsing()` bug fixed earlier in this branch: an
untimed `wait()` whose release depends on a worker reaching its last statement.
The handshake is now in a `finally`, a failed `thread.start()` counts itself,
and the new `getFailure()` lets a caller discover that a result is partial.

**Severity:** liveness, not silent wrongness — a hang, not a wrong number. But a
hang with no timeout and no error is the worst kind to diagnose from a bug
report.

### `Parallel.booleanAndRule()` always returned false

```java
boolean b3 = false;
b3 = b3 && (b1 == null ? false : b1);   // false && anything
```

The identity for AND is **true**; this seeded `false` and then ANDed into it,
mirroring the OR rule directly below — where `false` *is* the right identity.
A classic copy-paste-and-flip-the-operator slip, and the rule returned `false`
unconditionally.

**Severity:** a latent trap, not live wrongness — **no caller uses it today**.
Stated that way rather than inflated. A future "did every task succeed?"
reduction would have reported failure on a run where everything worked.
`booleanOrRule` was correct and is now pinned too, so the fix cannot be
"mirrored" back.

The 14 new tests all run under a hard 10-second timeout, because a regression in
this class is a hang rather than a failed assertion.


### Brillouin-zone selection audited against QE; no change, and one change avoided

`SymmetricKPointsGenerator` (663 lines) decides which Brillouin zone a deck has
and therefore which high-symmetry labels its band path may use. It is called
from the Band tab and from `BrillouinPathGenerator`, and it had no tests.

**It is a faithful port of QE's `find_bz_type` in `Modules/bz_form.f90`** — same
`ibz` numbering 1–16, same branch conditions, same `1e-8` tolerance on the
face-centred orthorhombic discriminant, same `canonical_celldm` axis reordering,
and the same letter names (`gG`, `M`, `X`, `R`, …). Verified branch by branch
against the Fortran.

**A change I nearly made and should not have.** The source carries two
commented-out lines:

```java
//} else if (ibrav == 3 || ibrav == -3) {
//} else if (ibrav == 5 || ibrav == -5) {
```

and `ibrav = -9` *is* handled alongside `9`, which makes the narrowing look like
a debugging leftover — `-3` and `-5` describe the same Bravais lattices as `3`
and `5` in a different axis setting, so widening the test looks obviously right.
It is not. QE's `find_bz_type` tests `ibrav==3` and `ibrav==5` exactly and groups
only `9 .OR. -9` and `12 .OR. -12`. Widening the Java would hand labels to a BZ
table QE refuses to build. **The exclusion is conformance, not an oversight**, and
it is now pinned by test so nobody else "fixes" it.

Unsupported lattices already fail closed: QE calls `errore(...)` for `ibrav = 13`
and `14`; this class returns `ibz = 0` and then `null`, rather than a Γ-only path
that would plot as a band structure with no dispersion.

14 new tests, no production change.


### An undeclared atom label crashed the band-count estimate

`BandCorrector.getNumBands` builds a per-species array sized by
`ATOMIC_SPECIES`, then sums it by walking `ATOMIC_POSITIONS` and resolving each
atom's label with `indexOfSpecies`. That returns `-1` for a label the species
card does not declare, and the result went straight into the array:

```java
nbands += nbandList[index];   // index == -1
```

so an `ArrayIndexOutOfBoundsException` came out of simply opening the Band or
DOS tab. The two cards are independent pieces of deck text and are routinely
inconsistent while a deck is being edited or pasted — `QEInputValidator` has a
dedicated `ATOM_SPECIES_UNKNOWN` code for exactly this state, which is proof it
is expected to occur — but that is a separate validation pass and does not gate
the estimate. `isAvailable()` only checks that both cards are non-empty.

**Severity:** robustness, not silent wrongness — an exception, not a wrong band
count. The unknown atom is now skipped rather than guessed at.

A second, quieter fix in the same method: an unreadable UPF reports
`zValence = 0`, which drives the semicore term to its `0` floor and produces the
bare orbital count anyway. That now takes the explicit fallback branch alongside
the null-pseudopotential case, instead of arriving there through arithmetic.

**Audited and found correct, no change:** the band formula itself. A
transition metal gets s+p+d, an f-block element s+p+d+f, everything else s+p,
with a semicore allowance of `(z_valence - valence)/2` on top; `noncolin`
doubles the total for the two-component spinors. Checked on Fe with
`z_valence = 16`, which yields 13 bands per atom against 8 occupied — a sane
margin. `SpinCorrector` and `CutoffCorrector` were read end to end and are also
correct; `CutoffCorrector`'s `9.0` USPP factor is deliberately more conservative
than `PseudoCutoffAdvisor`'s 8, and its `4.0 * ecutwfc` trigger matches QE's own
default for `ecutrho`.


### An unread elastic file produced a mechanical-stability verdict

When `ElasticParser` found no tensor block it left `cij` as an all-zero 6x6 and
still passed it to `QEElasticStabilityValidator`. Zero is not positive definite,
so the validator returned a confident **"Born mechanical stability check
FAILED"** — a statement about a material, derived from a file that was never
read. It now reports `null`, and `hasTensor()` says whether anything was parsed.

This matters more than it first looks, because the parser reads nothing from
*genuine* thermo_pw output. thermo_pw prints
`Elastic constants C_ij (kbar)` followed by an `i j=` index row
(`lib/elastic_const.f90`, `print_elastic_constants`); the literal this parser
searches for is `Elastic Constant Matrix`, which never appears.

**Severity, stated precisely:** both `ResultAnalysisService` call sites are
guarded by the same `"Elastic Constant Matrix"` string test and fail closed
before this parser is constructed, and the moduli path independently rejects an
all-zero tensor (`TENSOR_ZERO`). So this was a **latent trap plus a capability
gap**, not a wrong number that reached a user. `QEThermoPwElasticParser` is the
reader that handles thermo_pw's real 7-token row grammar; `ElasticParser` is the
older lenient path, and `ELateTensorDraft` already documents why it is not
reused for export.


### A spin-polarised metal's Fermi energy was never read

`PW/src/print_ks_energies.f90` has two Fermi formats:

```
9040  ' the Fermi energy is ',F10.4,' ev'
9041  ' the spin up/dw Fermi energies are ',2F10.4,' ev'
```

QE emits **9041 instead of 9040** when `two_fermi_energies` is set — an
`nspin=2` run with a fixed `tot_magnetization`. `FermiParser` matched only
`"the Fermi energy"` and `"highest occupied"`, so that line fell through both
branches and the run finished with **no Fermi energy recorded at all**, even
though the log plainly contained one.

Downstream that is a band structure or DOS with no Fermi reference — a missing
number rather than a wrong one, which is the better failure of the two but
still silent. The new branch records the higher of the two spin channels, that
being the level which actually bounds the occupied states of the combined
system, and is pinned for both orderings so it cannot degrade into "take the
first field".

**Audited and found correct, no change:** the column indices for the other
three formats. `subLines[4]` is the value in 9040, and the text after `:` is the
HOMO in both 9042 and 9043 — verified against QE's format statements, not from
memory. Also checked that the 9050 `(compare with: ...)` echo line and the 9044
conduction-Fermi line cannot be mistaken for a measurement.

`FermiParser` had no tests; there are now 10.

### One more spelling of the Bohr radius, folded into the shared constant

`QEBerryPolarizationParser` carried `0.5291772109`, a fourth spelling in a
codebase that already had three. It now takes `QEUnits.ANG_PER_BOHR`.

**This is a maintainability change, not a correction.** The numerical
difference is 5.7e-12 relative — far below anything that could affect a
polarization value. Recorded as such rather than dressed up as a bug fix.


### `hasOddElectronCount` answered a different question than its name

The predicate was:

```java
Math.abs(remainder - 1.0) < 0.5 - TOLERANCE || Math.abs(remainder - 1.0) <= TOLERANCE
```

The second clause is a strict subset of the first, so it never contributed
anything. What remained reduces to `0.5 < (n mod 2) < 1.5` — *"is n nearer an
odd integer than an even one"*, not *"is n odd"*. It returned true for 0.6 and
1.4, which are not odd electron counts.

More importantly the caller was asking the wrong question. The check exists to
catch `occupations='fixed'` where the bands cannot be filled in pairs, and
**every count that is not an even whole number** has that problem — fractional
counts as much as odd ones. A cell with `tot_charge` set, or a pseudopotential
with fractional `z_valence`, gives something like 8.4 electrons, and the old
test said "not odd" and stayed silent.

Split into two honest predicates: `hasOddElectronCount` is now strictly odd
(7.4 is neither odd nor even), and the new `requiresPartialOccupation` is what
the occupation review calls. The error message now distinguishes an odd count
from a fractional one and names the usual cause of the latter.

**Severity:** a missed warning, not a wrong number. The advisor stayed quiet on
a setup it exists to flag; it never produced a bad value itself.


### Cutoff advice was too low in two ways, both silently

`PseudoCutoffAdvisor` turns pseudopotential metadata into the `ecutwfc` /
`ecutrho` a user runs with, so an error here is a wrong number, not a wrong
choice. Both defects pushed the recommendation **down** — the dangerous
direction, since an under-converged cutoff still produces a run that finishes
and reports numbers.

1. **A rho-only cutoff was divided by another species' dual.** `evaluate`
   maximised the raw stated values first, then backed `rho` out through
   `maxTypeDual` — the largest dual anywhere in the structure. A
   norm-conserving species stating `rho_cutoff = 200` next to an ultrasoft
   species that states nothing gave `200/8 = 25 Ry`. The 200 belongs to the NC
   file, whose dual is 4, so the demand is `200/4 = 50 Ry`. **A factor of two
   low.** Dividing one file's rho by another file's dual is not a meaningful
   quantity.
2. **A rho-only species was dropped whenever any other species stated a wfc
   cutoff.** The back-out was gated on `if (ecutwfc <= 0.0)`. With Si stating
   `wfc = 40` and an ultrasoft O stating only `rho = 400`, the answer stayed
   40 Ry although O demands 50. `ecutrho` was still `max(400, 8*40) = 400`, so
   the pair emerged at an effective dual of **10** — matching no
   pseudopotential type.

Both are fixed by resolving each species' demand in its own terms and then
taking the maximum, which is what the class's documentation already claimed it
did ("the requirement is the *maximum* over all species"). The per-species
calculation is now a named method, `SpeciesRequirement.getRequiredWfcCutoff()`.

**Reachable with real files:** ONCVPSP norm-conserving UPFs commonly carry
`rho_cutoff` with no `wfc_cutoff` attribute at all, so "states rho but not wfc"
is ordinary, not a corner case. The advisor feeds the Convergence tab through
`QEFXConvergenceController.cutoffAdvice()`.

**Severity:** silent wrongness. `isKnown()` returns true, `describe()` prints a
confident number with units, and `isWfcBelowRecommendation()` passes a user's
too-small `ecutwfc` because the recommendation itself is too small.

The 10 new tests write genuine minimal UPF v2 files through `@TempDir` so the
real parser runs, and pin the unchanged cases too — a uniform ultrasoft set and
a fully-stated norm-conserving one — so the fix is not mistaken for a behaviour
change.

### The UPF v1 header parser skipped the mesh line and shifted every field after it

QE's `read_pseudo_header` (`upflib/read_upf_v1.f90`) reads eleven fields, one
per line, in a fixed order. Field 10 is `mesh`; field 11 is `nwfc, nbeta`.
`PseudoPotential.parseUpfV1PPHeader` went straight from `lmax` to the
wavefunction counts, so it read the **mesh** line as `nwfc`/`nbeta`:

| Field | Truth for `Fe.jry.pbe.UPF` | What was parsed |
|---|---|---|
| `meshSize` | 1165 | never set — stayed `0` |
| `numberOfWfc` | 5 | **1165** (the mesh size) |
| `numberOfProj` | 4 | the literal word `"Number"` → `QECharacter.getIntegerValue` returns **0**, silently |

Everything before `lmax` was already correct; only the tail was shifted.

**Where it surfaces.** `PseudoLibrary`'s comparator ranks candidate
pseudopotentials for an element by relativistic treatment, then z-valence, then
`ecutwfc`, then `ecutrho`, then `nwfc`, then `nprj`. UPF v1 files
overwhelmingly state `0.0000000 0.0000000` for "Suggested cutoff for wfc and
rho" — every real v1 file consulted while writing this does — so both cutoffs
fall back to the same defaults and the comparison reaches `nwfc` routinely. It
was therefore ordering candidates by **radial-grid point count**, and the first
entry is what `getPseudoPotential(element)` hands to a new deck.

**Severity, stated precisely:** this selects the wrong pseudopotential from a
set the user supplied; it does not corrupt a number inside one. Every candidate
is a valid PP for that element, so the run still completes — silent selection of
a different-quality dataset, not a wrong calculation. It only bites when two or
more UPF v1 files exist for one element and tie on z-valence. UPF v2 files are
unaffected: that path reads named XML attributes, not positions.

The four new tests use headers copied field-for-field from published UPF v1
files (Fe norm-conserving, O ultrasoft), so the expected values are external
facts rather than values read back out of this parser. They also pin the fields
*before* the shift, since a positional parser can be repaired in the wrong
place.

### Element 61 was spelled `Rm`; Z=61 is promethium, `Pm`

The periodic table in `ElementUtil` is called from 32 source files and had no
tests. Between `Nd(60)` and `Sm(62)` it listed `Rm(61, …)`. `Rm` is not an
element symbol. Every number on that row was correct — 145 u, covalent radius
1.73 Å, electronegativity 1.16, all fitting the lanthanide trend exactly — so
this was a wrong *identifier*, not a wrong value, and it broke lookup in both
directions:

- **Forward.** `toElement("Pm")` calls `Element.valueOf` on a name not in the
  enum and returns `null`. The forgiving getters then return their fallbacks —
  `getMass` → `-1.0`, `getCovalentRadius` → `1.0`,
  `getElectronegativity` → `0.0` — and the `obtain*` variants throw
  `IncorrectAtomNameException`. A promethium structure reaching
  `QEGeometryInput.setupAtomicSpecies` wrote `ATOMIC_SPECIES` with **mass
  −1.0**. `QEInputValidator` does flag that (`SPECIES_MASS`), but
  `AtomicExporter` does not — it formats the −1.0 straight into the exported
  deck.
- **Reverse.** `toElementName(61)` returned `"Rm"`, so a CUBE or XSF file
  carrying atomic number 61 (`CubeReader` line 168, `XSFReader` line 416)
  produced atoms labelled with a symbol that does not exist. Every later lookup
  of `"Rm"` then *succeeds*, because it genuinely is in the enum — right
  numbers, wrong label, and the deck goes to `pw.x` naming a non-existent
  element.

The fix renames the single enum constant. There was exactly one occurrence of
`Rm` in the repository and no occurrence of `Pm`, so nothing else referenced it.

The 12 new tests pin the invariants that would have caught this rather than the
one typo: symbols unique, atomic numbers contiguous and round-tripping
symbol → Z → symbol, no element returning a fallback value, and the exact set of
mass inversions (`Ar>K`, `Co>Ni`, `Te>I`, `Th>Pa`, `U>Np` — all real) so a
corrupted mass shows up as a *new* inversion.

**Audited and found correct, no change made:** covalent radii match Pyykkö 2009
single-bond values exactly on all 24 elements checked. An earlier comparison of
mine against Cordero 2008 flagged 46 "differences" and was simply using the
wrong reference — recorded here because the audit was wrong before it was right.
Electronegativities match Pauling on all 16 anchors, with Allen-scale values for
the noble gases (He 4.16, Ne 4.79, Ar 3.24), which is conventional since Pauling
defines none. Masses agree with IUPAC to better than 0.1% everywhere; the
largest gap is Tc at 9.5e-4, an element with no standard atomic weight.

**Severity:** wrong identifier, not a wrong number. Promethium is rare in
practice, so the realistic impact is narrow — stated plainly rather than
inflated.

### QE card names were matched case-sensitively

Card names are case-insensitive in Quantum ESPRESSO. `Modules/read_cards.f90`
normalises the whole card line with `capital(TRIM(input_line))` before comparing
it against `'ATOMIC_POSITIONS'`, `'K_POINTS'`, `'CELL_PARAMETERS'` and
`'ATOMIC_SPECIES'`, so `atomic_positions crystal` is input that `pw.x` reads
without complaint.

`QECard.readUptoMyCard` used `cardName.equals(subLines[0])`. A lower-case or
mixed-case card was simply not found: `read` returned `false`, and no caller
anywhere checks that return value — `QEInputReader.readCard` discards it. The
card therefore kept the values `clear()` had just installed moments earlier in
`QEInput.updateInputData`, and those defaults are not neutral:

- `CELL_PARAMETERS` resets to the 3×3 identity — a real lattice becomes a
  1 × 1 × 1 unit cube;
- `ATOMIC_POSITIONS` resets to an empty atom list under `alat`;
- `K_POINTS` resets to a 1 × 1 × 1 unshifted grid, i.e. Γ-only.

So a deck written in lower case loaded, displayed and ran while describing a
different structure and a different Brillouin-zone sampling than the file on
disk. Reachable from the input-file editor (`QEFXInputFileController`) and from
every project reload (`ProjectBody`), so it also affected decks pasted in or
exported from other tools.

The comparison is now `equalsIgnoreCase` on the same full first token, so
`K_POINTS` still does not bind to `ADDITIONAL_K_POINTS` — pinned by test. The
namelist reader was already case-insensitive (`QENamelist.isStartOfNamelist`
upper-cases before comparing); this removes the asymmetry between the two halves
of the same parser.

**Severity:** silent wrongness. No error, no warning, a plausible-looking
structure.

### `LogParser.endParsing()` could block forever

`endParsing()` waits on the `ending` flag with an untimed `wait()`, and only the
worker thread clears it. Two paths left no worker to do so:

- the final-parse block cleared the flag as its last statement rather than in a
  `finally`, so an `Error` — not caught by the surrounding `catch (Exception)` —
  killed the thread with `ending` still set (parsing a multi-GB AIMD log can
  exhaust the heap right there);
- `thread.start()` itself can throw `OutOfMemoryError: unable to create native
  thread`, after `startParsing` had already committed `parsing = true`.

`RunningNode` calls `endParsing()` from a `finally` block, so either path hangs
the job-execution thread and the stage never reports completion. The handshake
is now released in a `finally`, and a failed `start()` rolls the flags back.

**Severity:** a liveness fix, not a numerical one. Both triggers are
resource-exhaustion paths; neither was reproduced, and the reachability argument
is from the code structure.

### `QEValueBuffer` notified listeners over a live list

`QEValueBuffer` is the mutable cell behind every editable field in the QE input
editor — 36 source files reference it, and it had no direct tests. All four
notification sites iterated the live listener `ArrayList` while calling out to
listener code.

A listener may register another one while it runs: `QEFXItem.addWarningTrigger`
and `addEnablingTrigger` are public and both call `addListener`, and wiring up a
dependent control in response to a value change is exactly what they are for.
That modifies the list mid-iteration, so the next step throws
`ConcurrentModificationException` out of `setValue` — out of whatever edited the
field. Copying first also fixes the quieter half: a listener that unregisters
itself would otherwise cause the *following* listener to be skipped, since
`ArrayList`'s iterator does not re-index after a removal — and a skipped
listener is silent.

`QEFXProjectController.fireEditorTabChanged` already took a copy for this
reason; the two are now consistent.

**Severity, stated precisely:** a robustness fix, not a silent-wrongness one. It
would surface as an exception rather than a wrong number, and the reachability
argument comes from the public API, not from an observed reproduction.

The 12 new tests also pin the surrounding contract — write-through to the
namelist, typed zeros for an absent value, a foreign key being ignored rather
than rebinding the buffer, and the identity check in `onValueChanged` that makes
each edit produce exactly one notification.

### `Matrix3D` gains direct tests, including the transpose trap

`Matrix3D` is 391 lines of pure arithmetic used by 50 source files, reached
until now only incidentally through whichever caller happened to be under test.
The reason it warrants direct coverage is one matched pair:

```
mult(double[][], double[])  ->  M · v      (matrix on a column)
mult(double[],   double[][]) ->  vᵀ · M    (row on a matrix) = Mᵀ · v
```

They differ only in argument order, so choosing the wrong one **compiles and
returns a plausible vector**. Cartesian→fractional conversion uses
`mult(position, inverseLattice)` in `AtomicExporter`, `CalculatorFiles` and
`QEPdbReader`; for a non-orthogonal cell a transposed conversion relocates atoms
while keeping them inside the box — wrong physics, never an error. Both are now
pinned on an asymmetric matrix where the two answers cannot coincide.

Two behaviours documented because the names do not state them: `max()` is the
**signed** maximum (max of `(1, 0, −2)` is 1, not 2), and `equals()` is tolerant
to 1e-10 rather than exact. No production change — every case tested was already
correct.

### `Lattice` gains 12 tests; a claimed bug in it did not survive scrutiny

`com/math/Lattice.java` — 1,089 lines, referenced by 36 source files, the
crystallography behind every cell — had no direct tests. It was found by ranking
untested classes by fan-in rather than by guessing.

While writing the tests I claimed `getBravais` returned 0 for every cell. **It
does not.** `getCell(int, double[])` multiplies by `BOHR_RADIUS_ANGS` at the end,
which my offline Python port had dropped; `getCellDm` and `getCell` are exact
inverses. The change was reverted in full and the file is byte-identical to
before.

What remains is the coverage, with expectations taken from crystallography
rather than from the code: fcc primitive vectors meet at 60°, bcc at 70.53°,
hexagonal γ is 120°, and ibrav 1/2/3/4/6/8 each round-trip through their own
lattice vectors. They pass against the untouched implementation. Also pinned:
`getXMax` sums all positive components (the far corner of the cell box, not the
longest vector), and `getBravais` tolerates ~1e-7 drift so a vc-relax result is
still classified.

### Undo/redo (D5): the snapshot could throw, and a failed undo lied

D5 was listed as "undo/redo not started". It is in fact implemented —
`Modeler.undo`/`redo` delegate through `AtomsViewer` to `AtomsLogger` — but that
307-line engine had **no tests**, despite every modeller operation calling
`storeCell()` before it runs. Writing them found two defects.

**1. The null-atom guard was inverted.**

```java
if (atom == null || !atom.isSlaveAtom()) {
    listName.add(atom.getName());
```

`||` short-circuits, so a null atom made the condition *true* and the next line
dereferenced it — a guaranteed `NullPointerException` out of
`storeConfiguration`, surfacing from whichever modeller operation was starting
rather than from the logger. The guard exists precisely because nulls were
expected there, and it did the opposite of what it says.

**2. The lattice fallback read the cell after it had been emptied.**
`restoreConfiguration` calls `removeAllAtoms()` and *then* `restoreCell`, which
captured its own "previous lattice" at that point — atoms already gone. When the
stored lattice was refused, the stored *atom coordinates* were re-added into the
*previous* lattice: a mixed state that never existed, returned as a successful
undo.

The pre-restore lattice is now captured before the cell is touched, and
`restoreCell` reports whether the stored lattice was applied. That plugs into
rollback logic the callers already had — both push an optimistic entry onto the
opposite stack and poll it back on failure. Until now `false` was only returned
for an empty deque or a null config, cases the callers had already excluded, so
that rollback was effectively **dead code**. It now fires on the case it was
written for.

**Audited and found correct:** the stack discipline. `storeConfiguration` bounds
the undo stack and clears the redo stack, and the push/poll pairing means a long
undo/redo alternation cannot grow either side — simulated to 50 cycles, pinned
by a test.

### One `FieldVerdict`, before three copies could drift apart

Fixing the modeller's numeric entry produced three validators —
`MillerFieldValidator`, `SuperCellFieldValidator`, `ModelerFieldValidator` — and
each grew its own nested `Verdict` class with the same two fields, the same two
accessors and its own private `OK` constant.

Three copies of one idea is precisely how the two CUBE readers came to disagree
about the unit flag, and how `QEKpointMeshAdvisor` came to contradict
`KMeshAdvisor` by a factor of 2π. Both cost a real bug on this branch. The type
is unified **now**, while the three are still identical and the merge is
mechanical, rather than after one has quietly acquired a fourth field.

Unifying also let an invariant be *enforced* rather than merely intended:
`FieldVerdict.rejected(msg)` refuses a null or blank message. A rejection with no
reason reaches the user as an **empty error dialog** — worse than showing
nothing — and nothing previously stopped one being constructed. It now fails in
the validator being written, not in front of a user.

The three validators keep their public API exactly: same method names,
signatures and message text, so every call site reads the same. `FieldVerdictTest`
adds a drift check that runs all three and asserts every rejection carries a
reason and every acceptance says nothing — so if one later reverts to its own
verdict type, that test fails rather than whichever dialog happens to show it.

Net −71 lines.

### A NaN lattice passed the check that exists to reject bad cells

`Cell.checkLattice` guarded only with `if (volume < MIN_VOLUME) throw ...`. For
a lattice holding NaN or infinity, `|det|` is NaN — and **every comparison with
NaN is false**, so the test was false and the cell was *accepted*. That is the
worst outcome for this input: once stored, every length, angle, volume and
fractional coordinate derived from it is NaN, and the later checks that would
refuse a bad cell fail open the same way. The cell cannot be repaired, only
discarded.

It is reachable from the modeller. The strain, jiggle and vacuum buttons each
did `Double.parseDouble(field.getText())` straight into lattice or atom
arithmetic, wrapped in `catch (Exception e) { e.printStackTrace(); }`.
`Double.parseDouble` accepts `"NaN"` and `"Infinity"` as literals, and any
overflowing value such as `"1e400"` becomes infinity silently — and the catch
meant the user saw nothing either way. The button just appeared dead.

Three changes:

1. **`checkLattice` rejects non-finite components by name**, covering all *ten*
   `moveLattice` call sites at the model layer rather than one at a time.
2. **A latent bug in the same loop**: it tested `lattice.length` — the outer
   array, already checked two lines above — instead of `lattice[i].length`, so a
   short row passed the check whose message claimed to catch it and then threw
   `ArrayIndexOutOfBoundsException` from inside `calcVolume`.
3. **The three fields are validated up front** by `ModelerFieldValidator`, with
   failures shown instead of printed. The bounds are physical: strain is capped
   at ±99% because −100% collapses a lattice vector to zero length and anything
   beyond *reverses* it into a left-handed cell — which `abs(det)` still reports
   as a positive volume, so nothing downstream would refuse it.

Why the field checks matter even with the model guard: `moveLattice` moves every
atom **before** calling `setupLattice`, so catching a bad lattice only at the
model layer would still leave the atoms displaced. Refusing at the field avoids
entering that path at all.

### A supercell build could delete the structure and report success

Looking for the Miller-index bug's twin — an unbounded GUI integer feeding an
`int` product deep in a builder — found a worse one.

`SuperCellBuilder.build` guards the atom budget with `int nt = na * nb * nc;`
then `(nt * natom) >= maxNumAtoms()`. Both products are `int`, and the scale
fields accepted any `int`. With an 8-atom cell and the 2048-atom budget:

| Input | `nt` | Outcome |
|---|---|---|
| (2000, 2000, 2000) | −589,934,592 | `new Atom[nt][]` throws `NegativeArraySizeException` |
| (2147483647, 1, 1) | wraps to −8 | guard passes → tries to allocate **~17 GB** of references |
| **(65536, 65536, 1)** | **exactly 0** | guard passes, empty buffer, **no exception**, `build` returns **true** |

The last is silent and destructive. By the time `nt` is used,
`removeAllAtoms()` and `moveLattice()` have already run — atoms gone, lattice
inflated 65536×. Because `build()` reported success, `Modeler` skips
`restoreCell()`. The user clicks Build, sees no dialog, and their structure has
become an empty box.

Fixed in two layers. The **builder** now computes both products in `long`, and
caps `nt` independently — an *empty* cell has `natom == 0`, so `0 × any scale`
is 0 and the atom budget cannot bound the request, while `nt` still sizes the
buffer. The **fields** are validated up front by `SuperCellFieldValidator`,
which counts in `long` and says what is actually wrong — *"7 × 7 × 7 of 8 atoms
is 2744 atoms, at or beyond the 2048-atom limit"* — instead of the generic
"Atoms are too much" that every failure produced.

The bound is expressed in **atoms**, not as a scale limit, because that is the
quantity that matters: 7×7×7 is refused for an 8-atom cell and allowed for a
5-atom one, which a fixed scale cap could not express.

Behaviour preserved: a blank box still means 1, and 1×1×1 is still refused as
nothing to build. The controller is 15 lines shorter.

### The slab builder's Miller-index fields accepted anything

Extracting that validation (review item C2) showed it was barely validating.
`checkMillerValue` accepted any `int`; `isAvailSlab` only required "not all
three zero". The slab mathematics is stricter — `SlabMillerMath` bounds indices
at ±16 — and `SlabModelStem.setupIntercepts` then walks `scaleMin..scaleMax`
hunting the first common multiple, with `scaleMax` the **product** of the
non-zero indices held in an `int`. Both consequences are reachable by typing:

- The loop exits at the least common multiple, so equal indices are instant —
  but three large **coprime** ones are not. **(1009, 1013, 1019) walks ~1.04
  billion iterations** on the JavaFX application thread. Measured at
  1.6 × 10⁻⁷ s/iteration in Python and scaled by a conservative 30–100× for the
  JVM, that is roughly **2–6 seconds with the window frozen**, no progress and
  nothing to cancel.
- **(2000, 2000, 2000) overflows `scaleMax` to a negative number**, so
  `scaleMax < scaleMin`, the build returns null, and the user is told
  *"Atoms are too much"* — which is not what went wrong.

Both are now refused at the field with a message naming the real limit, and
`MillerFieldValidator.MAX_INDEX` is taken *from*
`SlabMillerMath.MAX_MILLER_INDEX` rather than restated, so the two cannot drift
apart — a test asserts that coupling directly.

The rules are now a plain class with no JavaFX in it, covered by a table of
cases (blank vs zero vs non-integer vs out of range, and which field is reported
when several are wrong) instead of requiring someone to type into three boxes
and watch a button. The controller keeps only the wiring and is 23 lines
shorter. Behaviour deliberately preserved: a blank field is still not an error,
and (1 0 0) is still a valid plane while (0 0 0) is not.

### Both force-constant routes now answer the same questions

The project reads force constants two ways — phonopy's `FORCE_CONSTANTS` and
q2r.x's `.fc` — and both feed the same report. Comparing them finished the
audit.

- **The q2r route now reports the acoustic sum rule too.** Same physics as the
  FORCE_CONSTANTS check, but *not* the same arithmetic: q2r enumerates blocks as
  `(k, ll, i, j)` with each block holding `dim1·dim2·dim3` lattice translations,
  so the sum runs over every block sharing a `(k, ll, j)` **and** over all values
  inside them. The grouping was derived from this file's own index order and
  checked against the parser's loop nesting rather than assumed to carry over.
- **`FORCE_CONSTANTS` now says it has no known unit.** q2r can print `Ry/au²`
  because that format is QE-only; phonopy's `FORCE_CONSTANTS` takes the
  *producing calculator's* convention — `Ry/au²` for QE, `eV/Å²` for VASP,
  CRYSTAL, FHI-AIMS and LAMMPS, `mRy/au²` for WIEN2k, `hartree/au²` for Elk and
  TURBOMOLE — and the file records no marker saying which. The same physical
  force constant is written as numbers **48.59× apart** (1 Ry/au² = 48.586812
  eV/Å², from phonopy's own interface table). Both readers' magnitudes appear
  side by side in one report, one labelled and one not. Rather than guess, the
  reader now states the ambiguity.

To be clear about what each is: the ASR check is an **added guard**, with no
evidence a user hit it. The unit note is a **correctness-of-reporting fix** —
numbers were presented as if their scale were established.

A fixture note from writing the tests: the existing natom=1, 1×1×1 example
*cannot* satisfy the ASR unless every value is zero — one atom on a single-cell
grid has nothing to cancel against — so the new tests use a 2×1×1 grid where the
two translations genuinely can.

### FORCE_CONSTANTS is now checked against the acoustic sum rule

`QEPhonopyForceConstants` parsed the file, counted its blocks, censused the
header indices and reported the largest element — but never checked the one
physical invariant the numbers must obey. Translating the whole crystal rigidly
costs no energy, so every row of the force-constant matrix must sum to the zero
3×3 tensor: `Σ_j Φ_ab(i,j) = 0`.

When it does not, the acoustic branches do not vanish at Γ and the run reports
imaginary modes that read as a real lattice instability. That is the mirror of a
bug already fixed on this branch in the `matdyn` path — where a −95 cm⁻¹ mode
was reported as *stable*; here a broken file fabricates the opposite error, an
instability that is not there. Files written without phonopy's `--fc-symmetry`,
or truncated in transit, are the realistic sources.

`getMaxAcousticSumResidual()` gives the largest |row sum| in the file's own
units; `getRelativeAcousticSumResidual()` scales it by the largest matrix
element so files with different units or supercell sizes compare. `describe()`
surfaces both.

**Reported, never judged** — matching the rest of the class, which reports the
index census verbatim and leaves phonopy's symmetry call to phonopy. No
tolerance is hardcoded, because what counts as acceptable depends on the units
and the supercell. The residual is NaN while a block is held back mid-write:
the missing block is precisely what would cancel the sum, so a residual from a
partial matrix would be worse than none.

**Audited and found correct:** `QEPhonopyForceSetsWriter` and
`PhonopyForceSetsReader` really are exact mirrors. A writer → reader round-trip
preserves atom indices, displacements and forces — including values wide enough
to overflow the `%15.10f` field, because Java's `%f` pads rather than truncates
and the reader splits on whitespace — and the reader enforces the writer's own
constraint that a displaced-atom index cannot exceed the atom count.

### A 2π error graded every realistic k-mesh as "coarse"

`QEKpointMeshAdvisor` reports an effective k-range and classifies it against
12 Å (recommended) and 24 Å (accurate) — the same targets
`QEKPoints.setRecommendedCondition` inverts when it *proposes* a mesh. But it
computed the range as `1 / (|b_i| / n_i)`, dividing by `|b_i| = 2π/d_i` and so
understating it by exactly **2π**. Because the thresholds are fixed numbers
rather than a relative criterion, the factor does not cancel.

| Cell | Mesh | Old verdict | Correct |
|---|---|---|---|
| cubic 4 Å | 8×8×8 | 5.09 Å → **COARSE** | 32 Å → ACCURATE |
| Si fcc primitive | 11×11×11 | COARSE | 34.5 Å → ACCURATE |
| graphene slab | 15×15×1 | COARSE | 31.9 Å → ACCURATE |

Reaching "recommended" would have required `n·|a| ≥ 12·2π = 75 Å` — a 19×19×19
mesh on a 4 Å cell, about **13× the k-points**, and 31×31×31 (~30 000 points)
for graphene. The two advisors in the package flatly contradicted each other:
every mesh `KMeshAdvisor` proposes was graded COARSE by this one, and so was the
chooser's *own* recommended mesh.

Only the classification was affected. The spacing in Å⁻¹ was always correct and
is unchanged, so `ResultAnalysisService`'s spacing column and its Brillouin-zone
facet cross-check were never wrong — but its range column, printed labelled
"Ang", now actually is Ångström.

The old tests pinned the broken formula; one comment read
*"range = 8*10/(2*pi) = 12.73 Ang"*, dividing a length by 2π and still calling
it Ångström. They are rewritten around the threshold boundaries, plus a new test
asserting the grader cannot contradict the chooser it shares thresholds with.

### The two CUBE readers disagreed about the same file

The project has two CUBE readers — `atoms/reader/CubeReader` for the structure
and `run/parser/CubeGridReader` for the density grid — and they applied
different rules to the format's unit flag. `CubeGridReader` requires **all
three** voxel counts to be negative before treating a file as Ångström;
`CubeReader` keyed off the first axis alone. A header of `(-40, 40, 40)` was
therefore Ångström to one and bohr to the other: the same file, opened two ways
in the same application, giving cells a factor of 1.89 apart per axis.

`CubeReader` now follows `CubeGridReader`'s rule, which is the safe direction as
well as the consistent one — the atoms and the origin share a single unit, so a
mixed-sign header cannot describe the file, and falling back to bohr matches
what every real producer writes.

**Audited and found correct:** `CubeGridReader` gets right the two things
`CubeReader` had wrong — the lattice is `N * step` with the origin *not*
subtracted, and the data ordering is x-outer/z-inner per the format.

One difference deliberately left alone: `CubeGridReader` hardcodes
`0.529177210903` (CODATA-2018) while `Constants.BOHR_RADIUS_ANGS` is
`0.52917720859` (CODATA-2006). That is 4.4 × 10⁻⁹ relative — about 9 × 10⁻⁸ Å on
a 20 Å cell — so it is far below physical significance and not worth a
behaviour change. `QEUnits` already documents the provenance of both.

### The active tab went stale on every back-navigation

`setEditorText()` updates the tab label, refreshes the calculator badge and
fires `EditorTabChanged`. `restoreProjectAnsatz()` — which runs whenever the
user backs out of the result viewer, the modeller, the slab builder or the
designer — instead wrote straight to the label:

```java
this.editorLabel.setText(editorMenuText);
```

Same state, second path, no notification. So returning from any of those modes
left the input-file popup showing the tab from *before* the mode switch, and the
calculator badge unrefreshed, until something else happened to fire a change.
That is precisely the staleness the popup was fixed for earlier on this branch;
a second silent writer re-introduced it for the whole back-navigation path.
Now routed through `setEditorText`, trimming the trailing space it appends so
the label cannot accumulate one per restore.

### `ProjectMode`: the back button's graph is now testable

The workspace mode was an `int` with six `private static final` constants, and
the back-navigation graph lived inside a `switch` in the viewer button's
`setOnAction` lambda — so *"does the slab builder return to the modeller or drop
me all the way to the workspace?"* could only be answered by launching the
application and clicking in the right order.

It is now an enum carrying its own `back()`. The graph is a **tree rooted at
`NORMAL`, not a history stack**: slab always returns to the modeller and the
result viewer always to the result explorer, however the user arrived. That
distinction is the substance of the new tests, along with
`isReachableFromNormal()`, which exists so the *absence of a cycle* is asserted
— two modes made each other's parent would leave the back button bouncing with
no way out, a defect reachable only by clicking the exact sequence.

A follow-up commit finished the job rather than leaving the mode represented
twice: the controller now holds a `ProjectMode` and keys its three per-mode
state maps by it, and the `MODE_*` ints are gone. `getCode()`/`fromCode()` went
too — they existed to preserve the legacy numbering for those maps, but the maps
are in-memory only, so nothing was persisted and nothing needed the numbers.
Keeping them would have meant shipping public API whose only caller was its own
test. Net −21 lines, behaviour unchanged, verified destination-by-destination
for all six modes.

### Structure readers: the cell quietly reshaped on import

Continuing the same audit with **ASE 3.29** as the reference reader, across
every remaining structure importer.

- **`CubeReader` subtracted the density-grid origin from the lattice.** In a
  CUBE file each axis line is `N vx vy vz` — a voxel count and one voxel's step
  vector — so the axis vector is `N * step`. The origin only says where the grid
  sits. Subtracting it from all three vectors *shears* the cell. With
  `origin = 0`, the overwhelmingly common case and the one in the format's own
  published example, the arithmetic is unchanged, which is exactly why this
  survived: with a molecule-centring origin of `-5 -5 -5` bohr, a 6.00 Å
  orthogonal cube became a **53.5° rhombohedron with 2.3× the volume**
  (216.0 → 501.8 Å³). The origin was subtracted from every *atom* too, so the
  structure no longer sat inside its own density. Separately `Math.abs()` on the
  voxel count discarded the format's unit flag (a negative count declares
  Ångström), converting such a file by 0.529 a second time. The flag's meaning
  is genuinely disputed between Gaussian's docs and Bourke's description, so the
  reasoning is recorded in the code — worth noting ASE ignores the sign entirely
  and therefore reads a negative count as a **negative lattice vector**.
- **`QEPdbReader` ignored CRYST1's cell angles.** It read the three lengths and
  built a diagonal box unconditionally, so every non-orthogonal cell — most MD
  snapshots and most molecular crystals — was silently rebuilt as rectangular
  while the atoms kept Cartesian positions that no longer belonged to it. A
  10 × 12 × 15 Å cell at β = 105° has a true volume of 1738.67 Å³; it was read
  as 1800 Å³, 3.5 % high, with **c** pointing along +z instead of tilting to
  (−3.882, 0, 14.489). Now built through `Lattice.getCell(a,b,c,α,β,γ)` — the
  helper `CIFReader` already used — with a fallback to the orthogonal reading for
  a CRYST1 truncated before its angle columns. A right-angled CRYST1 still gives
  exactly the diagonal cell, pinned by a test.

**Audited and found correct, no changes needed** — reported because a clean
result is a result:

- **`VASPReader`** in all six combinations that matter: positive scale, negative
  scale (meaning a target volume), Direct and Cartesian coordinates, and
  selective dynamics in both. Every one matches ASE, including the `T`/`F`
  per-axis constraint flags.
- **`CIFReader`** symmetry expansion, which is where this class of reader
  usually breaks: rutile `P4_2/mnm` expands to exactly ASE's 6 atoms, and
  corundum `R-3c` to exactly ASE's 42, rhombohedral centring translations
  included. The floating-point boundary case in its periodic de-duplication was
  probed too (`2/3 + 1/3` and `-(1/3) + 1/3` are exact in IEEE 754), so the
  wrapping cannot spuriously duplicate an atom onto a cell face.

### Structure interchange: two writers and one reader that silently dropped the cell

Audited every structure import/export path against **ASE 3.29** as an
independent reference reader, rather than against the format documentation
alone. Three defects, none of which raised an error or produced a file that
looked wrong on inspection.

- **Exported XYZ was not periodic.** `AtomicExporter.toXYZ` wrote its comment
  line as `QuantumForge export: lattice="..."`. Extended XYZ requires
  `key=value` pairs with a case-sensitive, mandatory `Lattice`; a lowercase
  `lattice` behind free text and a colon matches nothing, so every reader fell
  back to "no cell supplied" — which the format *defines* as an isolated,
  non-periodic cluster. ASE returned a zero cell with `pbc=[False, False,
  False]`. The atoms were all present at the right coordinates, so only the
  periodicity was gone. The sibling writer `ExtXyzCellExporter` had the
  convention right all along: two XYZ writers disagreed and only the correct
  one was tested.
- **Imported extended XYZ lost its cell whenever `Properties` came first.**
  `XYZReader` split the comment on the *first* `=`/`:`/quote/bracket anywhere in
  the line and read nine numbers after it — which only works if `Lattice` is the
  first key. ASE routinely writes `Properties=species:S:1:pos:R:3` first, and
  then the "numbers" were `species:S:1:pos:R:3`, the parse returned null, and
  a null lattice is not an error here: it means *molecule*. The reader recentred
  the atoms and invented a box 5 Å clear of the bounding box. ASE's own silicon
  primitive cell (**40.03 Å³**) imported as an 11.36 Å cube of **1465 Å³** —
  37× the volume, flagged `MOLECULE`, lattice vectors gone. Every k-mesh,
  density, symmetry determination and SCF run from such an import was wrong.
  The key is now matched by name, case-insensitively (files this application
  itself wrote must keep importing); the old positional scan survives as a
  fallback for non-extxyz comment styles.
- **Generated CASTEP `.cell` files contained no atoms.** `POSITIONS_FRAC` was
  emitted as an empty block holding only a `#  element  x  y  z` comment, so
  every file described a periodic box with nothing in it. ASE's reader raises
  `IndexError`; CASTEP has nothing to relax. The atoms were in the `Cell` the
  whole time and simply were never written.

Found and fixed alongside them:

- The phonopy structure tab was labelled **`SPOSCAR (supercell)`** while holding
  the *un-expanded unit cell*. `SPOSCAR` is written by `phonopy -d --dim=...`
  and is never a user input; anyone trusting the label would have run phonons on
  a cell `DIM` times too small. Relabelled `POSCAR (unit cell)` — the `DIM` in
  `phonopy.conf` is what performs the expansion.
- Opening an animated **`.axsf`** surfaced as `IllegalArgumentException: cell is
  null` from `QEGeometryInput`, because `XSFReader.readAnimationCell()` was a
  `// TODO` returning null and nothing on the path to `ProjectBody` checks for
  a null cell. It now fails as an unsupported format, by name. Reading only the
  first frame would have looked like success while discarding the trajectory.

**Audited and found correct** — `toPOSCAR`, `toCIF`, `toQEInput` and
`XCrySDenLauncher.toXsf` all round-trip through ASE with lattice, species
grouping and coordinates preserved. New suites (`AtomicExporterXyzTest`,
`XYZReaderTest`, `XSFReaderTest`, `CalculatorFilesTest`) pin all of the above,
including a `XCrySDenLauncher` → `XSFReader` round-trip, since those two are
each other's counterpart and nothing checked that they agreed.

### Tests for the two remaining untested structure cards

`CELL_PARAMETERS` and `ATOMIC_SPECIES` had no coverage. Both were **audited
first and found correct**, so these pin behaviour rather than repair it — but
both sit under bugs already fixed on this branch, so the guarantees are worth
stating.

- **`QECellParametersTest`** — the lattice everything else is measured against.
  Confirmed the `%10.6f` format keeps ~2e-7 relative precision on a 5 Å cell
  (far below any convergence threshold) and, unlike Fortran's fixed `6f10.4`
  — the format behind the `matdyn.freq` bug, where adjacent fields ran together
  — Java **pads rather than truncates**, so even a `12345.678000` vector still
  reads back as three parseable numbers. A fresh card declares **no** unit,
  which is deliberate: QE reads a unit-less card as *alat* when `celldm(1)`/`A`
  is present and as *bohr* otherwise, and `CellBuilder` implements exactly that.
- **`QEAtomicSpeciesTest`** — order is preserved, because
  `starting_magnetization(1)` means the *first* species and reordering moves a
  moment onto the wrong element; a duplicate label collapses rather than adding
  a row that would shift every later per-species index and desync `ntyp`; a
  missing pseudopotential becomes a visible placeholder instead of a blank
  column that truncates the line, while `hasPseudoPotential()` still reports it
  as absent.

Both suites assert the column-separability of the written card with a
deliberately over-wide value (a 12345 Å vector, uranium's 238.02891 mass)
rather than trusting the format string.

### The default band path now admits what it is

The Band tab's **Default** button fills the k-point table from
`BrillouinPathGenerator`, which picks the Brillouin zone from `ibrav` and the
cell ratios **alone — it never reads the atoms**. Every structure sharing a
Bravais lattice therefore gets the same path even when the space groups differ:
diamond (Fd-3m) and zincblende (F-43m) are both `ibrav = 2`, and an ordered
alloy written with `ibrav = 2` is really rhombohedral, where the cubic labels do
not exist.

`SymmetryAdvisor`'s javadoc already said this "cannot be right in general", but
the button filled the table silently, so a populated list implied more
verification than had happened. It now names the assumption and points at the
adjacent **Detect space group / band path** control, which derives the answer
from the structure via spglib/seekpath. The path itself is unchanged — this is
about not overclaiming.

### Tests for three untested cards that decide what QE runs

941 lines of Brillouin-zone logic, plus the two cards that define the mesh and
the geometry, had no coverage at all.

- **`BrillouinPathGeneratorTest`** — the basis-blindness above is *asserted*,
  not papered over: the diamond/zincblende case **requires** the two paths to be
  identical, so if the generator ever becomes basis-aware the test fails and the
  caveat gets revisited. Also pins the simple-cubic circuit exactly, fcc having
  W/L and no M, bcc having H/P, and the zero-weight terminator — QE reads a
  special point's weight as the count to the *next* one, so losing the final
  zero sweeps two disconnected lines into one continuous path.
- **`QEKPointsTest`** — grid components clamp to ≥ 1 (a slab still needs one
  point along its vacuum axis), and offsets normalise to the 0/1 flag QE
  defines. A half-grid shift written where zero was meant silently excludes
  Γ, which changes metals and every Γ-centred property.
- **`QEAtomicPositionsTest`** — a fixed atom keeps its `0 0 0` (losing it turns
  a frozen-substrate relaxation into a full one, with no error), and
  `addPosition` copies its arrays rather than aliasing a caller's scratch
  buffer, which would land every atom on the last coordinates written.

Every expectation was extracted from the source and checked before being
written down. Doing so caught a flaw in one of the new tests: a free atom's line
was checked for not ending in `"0"`, but the coordinate `0.000000` ends in a
zero, so it would have failed for an unrelated reason.

### Tests for the decisions that were previously unreachable

Three pieces of logic that change what QE actually runs had **no** coverage,
because each sat inside a JavaFX class that cannot be built headless. That
untestability is how two of this branch's bugs survived in the first place, so
the logic was extracted rather than left unverified.

- **`RungVerdict`** (new) holds the convergence-sweep rule that decides whether
  a rung may contribute a point. Same three refusals and wording as before, now
  a pure function of *(exit code, SCF report, metric)*. Seven tests, including
  the case that was the original bug: an SCF that hits `electron_maxstep` still
  prints a total energy, so the metric parses cleanly and used to be plotted as
  though converged.
- **k-mesh unit regression**: rather than assert a magic grid size, the test
  feeds the *same* lattice through both entry points and requires the Bohr one
  to come out strictly denser — that is the mistake that was made, so it fails
  if reintroduced and needs no update when spacing or rounding changes.
  (4 Å cubic at 0.2 Å⁻¹: 8×8×8 correct, 15×15×15 double-converted.)
- **`SpinCorrector`** decides `nspin = 2` vs `noncolin`+`lspinorb` vs nothing —
  physics *and* cost — and had no tests. I first read the relativistic branch as
  a bug; the QE user guide (§3.3) says otherwise, so the behaviour is unchanged
  and the reasoning is now documented in the code. The fully-relativistic branch
  is deliberately **not** faked: it reads a real UPF through `PseudoLibrary`, and
  a stub would only test the stub. That limit is stated in the javadoc.

### Fixed: a failed SCF could still contribute a point to a convergence curve

`ConvergenceSweepRunner` captured `pw.x`'s exit code and the parsed SCF report,
then consulted **neither** once a metric had been extracted. The exit code was
only mentioned when no number could be found at all.

A readable number is not a trustworthy one. `pw.x` prints a total energy even
when it stops at `electron_maxstep` without converging; a run killed mid-write
leaves the last energy parseable; a post-SCF step can fail after the energy is
printed. In each case the value was added to the convergence curve as though it
were converged, the sweep then quoted a cutoff derived partly from it, and
nothing on screen said a run had failed.

A rung is now discarded, and the sweep stopped with a stated reason, when the
process exits non-zero or when the log says `convergence NOT achieved`. Both
signals were already computed — `ScfConvergenceAnalyzer.isExplicitlyNotConverged()`
is parsed on the line immediately above — and simply never checked.

### Fixed: the advised k-mesh was about 1.9x too dense

The Convergence tab read the structure's lattice with `cell.copyLattice()`,
named the result `latticeBohr()`, and passed it to
`KMeshAdvisor.fromLatticeBohr` — which converts Bohr to Ångström again. The
`Cell` model already stores **Ångström**, so the lattice was shrunk by 47%, the
reciprocal vectors grew by the same factor, and the advised mesh came out
roughly **1.9× denser per axis**: a 4 Å cubic cell was advised 15×15×15 where
8×8×8 meets the same k-spacing.

That is not wrong physics — a denser mesh is still convergent — but SCF cost
scales with the number of irreducible k-points, so advising ~2× per axis is up
to **~8× the CPU time**, silently. The method is now `latticeAngstrom()` and
calls `fromLatticeAngstrom`.

Same root cause as the `StructureSanityCheck` unit bug: **`Cell` stores
Ångström, and code that assumes Bohr converts a second time.** A sweep of the
remaining consumers found no others — `GeometryChecker` and
`QEFXLatticeViewerController` convert `ProjectGeometry`, which really is Bohr
(built from QE's `celldm(1)`), and `SpglibService` correctly sends Ångström
unconverted.

### Fixed: the structure sanity check used the wrong length unit throughout

`StructureSanityCheck` converted every length by `BOHR_RADIUS_ANGS`, on the
assumption that the `Cell` model stores Bohr. It stores **Ångström** —
`CellBuilder` multiplies Bohr and `alat` inputs by that constant on the way in,
and maps `ANGSTROM` input with `unit = 1.0`. Converting again shrank every
length by **47%** and every volume by a factor of **6.7**:

- a real 2.35 Å Si–Si bond was measured as 1.24 Å, and a 1.43 Å C–O bond as
  0.76 Å — **below the overlap threshold, so ordinary bonds were reported as
  clashes**;
- real silicon (20.0 Å³/atom) was measured as 2.97 Å³/atom and flagged as
  impossibly dense.

**The tests did not catch this because they made the same mistake.** Their
helper converted Ångström → Bohr before adding atoms, so the two errors
cancelled exactly and the suite passed while the checker misjudged every real
structure. That helper is now the identity, named `angstrom(...)` so the unit
stays visible rather than being implied by bare numbers.

Verified against real chemistry after the fix: silicon's nearest neighbour
reads 2.3513 Å against a 1.11 Å limit, density 20.01 Å³/atom, and the
"a real silicon cell must pass cleanly" test now passes *because the physics is
right* rather than because two bugs offset.

### Fixed: unreadable PDOS files were dropped without a word

`QEPdosParser.parseDirectory` discarded an `IOException` into an empty catch,
and treated a file whose header it could not resolve the same way — it simply
returned the components it had managed to read. A projected DOS is **summed
over those components**, so a dropped file makes the total quietly too small,
and the caller (which sees only the component count) had no way to distinguish
an incomplete read from a complete one.

Both skip reasons are legitimate; saying nothing about them is not. The parser
now carries a `getDiagnostics()` channel, and the Projected DOS viewer states
plainly how many files were skipped and that the projections shown are
therefore incomplete.

Found by an AST-assisted sweep for empty catch blocks: 104 across the codebase,
47 in scientific paths. Most are the legitimate "skip one malformed row of a
table" idiom; this one was different because the unit being silently dropped
was a whole file that contributes to a sum.

### Fixed: NEB paths dragged boundary-crossing atoms the long way round

`NEBPathCreator` interpolated **raw Cartesian differences** with no
minimum-image convention, so diffusion across a periodic boundary — the
commonest NEB case there is — was built wrong by default:

- an atom at x = 0.5 Å moving to x = 9.5 Å in a 10 Å cell has hopped
  **1.0 Å through the face**; the raw difference is **9.0 Å**, so every
  intermediate image dragged it the long way through the middle of the
  structure, straight through whatever else is there;
- the reported per-step displacement was 2.25 Å instead of 0.25 Å, so the
  1.5 Å "coarse displacement" warning fired on a finely spaced path — a user
  acting on it would add images to fix a problem that does not exist while
  the real one went unmentioned;
- any barrier obtained from such a path is meaningless.

Both the interpolation and the displacement check now use the minimum-image
convention, measured consistently against the initial lattice. Third instance
of this defect class in this branch, after `SQSBuilder` and
`StructureSanityCheck`: **a periodic structure treated as a free cluster.**

### Fixed: NEB paths dragged boundary-crossing atoms the long way round

`NEBPathCreator` interpolated **raw Cartesian differences** with no
minimum-image convention. Diffusion across a periodic boundary — the commonest
NEB case there is — was therefore built wrong by default:

- an atom at x = 0.5 Å moving to x = 9.5 Å in a 10 Å cell has really hopped
  **1.0 Å through the face**; the raw difference is **9.0 Å**, so every
  intermediate image dragged it the long way through the middle of the
  structure, straight through whatever else is there;
- the reported per-step displacement was 2.25 Å instead of 0.25 Å, so the
  1.5 Å "coarse displacement" warning fired on a path that is in fact very
  finely spaced;
- any barrier obtained from such a path is meaningless.

Both the interpolation and the displacement check now use the minimum-image
convention. The existing tests were re-verified against the new code first —
all four of their assertions are unchanged, because none of them crossed a
boundary. Two regression tests added for the case that did.

This is the same defect class already fixed in `SQSBuilder`: **a periodic
structure treated as a free cluster.**

### Fixed: the alkane builder produced geometry no SCF could use

`MoleculeBuilder.createAlkaneChain` advertised "a simple alkane chain" and
produced something that is not a molecule:

- **C–H bonds of 0.707 Å and 0.500 Å** against a real 1.09 Å — 35% and 54% too
  short. Hydrogens were placed at fixed ±0.5 Å offsets rather than along any
  bond direction. At that separation the nuclei are far inside any bonding
  distance, so an SCF either fails to converge or converges to something
  unrelated to the requested molecule.
- **A straight carbon backbone** (180°) instead of the tetrahedral 109.5°
  zig-zag.
- **CH₃ for methane** — a radical with an unpaired electron, not CH₄.

Carbons now zig-zag at the tetrahedral angle, every hydrogen sits at exactly
1.09 Å along a genuine sp³ direction, and the formula is CₙH₂ₙ₊₂ for all n.
Two problems found while verifying, both caught by simulation before pushing:
methane's hydrogens came out at 70.5° rather than 109.5° (cone measured from
the wrong direction), and propane's two methyl rotors eclipsed, putting a pair
of hydrogens **0.894 Å** apart — closer than an H–H bond. Terminal rotors are
now oriented to maximise clearance. The molecule is also centred in its box,
because `Cell.addAtom` wraps out-of-cell coordinates and terminal hydrogens sat
at slightly negative x, which would have teleported a methyl group to the
opposite face.

`MoleculeBuilder` had **no tests at all**; it now has seven, pinning formula,
bond lengths, backbone angle, methane's tetrahedron, and absence of clashes.

### Fixed: solvent filling silently substituted the wrong molecule

`SolventFiller` offers seven solvents. Only water was real:

- **methanol** was built as `createAlkaneChain(1)` — methane, CH₄
- **ethanol** as `createAlkaneChain(2)` — ethane, C₂H₆

Neither has the hydroxyl oxygen that makes it a solvent, so every
hydrogen-bonding and dielectric property of the box was wrong. The molecule
count made it worse: the box was filled to methanol's 32.04 g/mol while placing
molecules weighing 16.04, i.e. **half the requested density** of the wrong
species. Acetone, EC, DMC and acetonitrile fell through `default` and became
water with no notice. Unsupported species are now refused with a diagnostic
rather than silently substituted.

### Fixed: transition-state "prediction" returned the reactant

`TSGuessing.predictTS` documented itself as predicting the transition state
between two endpoints and **returned the initial cell unchanged**. There is no
model, no weights and no inference anywhere in the codebase. This is the most
damaging possible answer: a TS guess exists to seed a saddle-point search, so
seeding it with the reactant either relaxes back and reports a zero barrier, or
wanders and reports a meaningless one — both looking like completed
calculations. It now fails closed.

### Fixed: the SQS generator scored a periodic cell as a free cluster

`SQSBuilder` advertised itself as "mathematically rigorous" with "multi-site
pair correlation". Six defects, none of which produced a visible error:

- **No minimum-image convention** — the worst of them. Pair distances were raw
  Cartesian separations, so a *periodic* supercell was scored as a free-standing
  cluster. In the project's own 8-atom test cell, 3 of the 16 nearest-neighbour
  pairs were invisible: the atom at x=0 and the atom at x=10.5 in a 12 Å cell
  are **1.5 Å apart through the boundary**, but were read as 10.5 Å. Every cell
  face behaved like a free surface, biasing the correlation for *any* input.
- **Hardcoded 3.5 Å first shell** — fine for Si/Fe/Cu, but caesium's first shell
  is 5.31 Å, so *no* pairs were found and the routine returned the sentinel
  `1.0`, which the caller could not distinguish from "optimised but poor". The
  cutoff is now **derived** from the shortest observed minimum-image distance.
- **Reference species re-read from `atoms[0]`** on every evaluation, so the spin
  convention could flip mid-optimisation. Now pinned to `elements[0]`.
- **Ternary and higher silently mishandled** — the ±1 site variable cannot
  separate a third species, and the target correlation was left at `0.0` for
  non-binary input, so the optimiser chased a number nobody computed. Now
  **refused explicitly**, pointing at ATAT `mcsqs`.
- **Greedy descent described as "Monte Carlo"** — only strictly improving swaps
  were accepted, so it is a quench that cannot escape a local minimum. The
  documentation now says what it is.
- Returns a `Result` (success, error, derived cutoff, pair count, message)
  instead of a bare `double` whose `1.0` meant both "bad match" and "could not
  be evaluated".

The correlation *target* was already correct and is unchanged: for site
variables ±1 on a binary alloy, ⟨s_i s_j⟩ = ⟨s⟩² = (2x−1)².

### Fixed: the double-layer builder generated overlapping ions

`EDLBuilder` placed counter-ions at uniformly random positions and returned as
though it had built a solvated interface. Sampling the same distribution:
**14%** of 5-ion builds contain a sub-2 Å contact, **47%** at 10 ions, **93%** at
20. It also hardcoded a 15 Å interface height regardless of the slab, and
accepted a `solvent` argument it ignored, with no charge balance — the defining
property of a double layer. It had **no callers**, which is the only reason it
never produced a bad structure. It now fails closed and points at PACKMOL.

### Fixed: 24 more modeller buttons that prompted, then fabricated a result

- A second sweep found controls the first pass missed, because their handlers
  were *not* pure dialogs — they popped a `ChoiceDialog`/`TextInputDialog` for a
  parameter, read a text field, and **then** announced success without ever
  touching the cell. The prompt made them far more convincing than the
  dialog-only kind. Verbatim:
  - *"Primary knock-on atom (PKA) cascade simulation complete: Defects
    generated: 4 Frenkel pairs (2 vacancies, 2 interstitials) successfully
    calculated and stabilized inside the cell lattice!"*
  - *"Successfully rolled crystal cell into periodic Single-Walled Nanotube
    (SWNT) with Chiral Vector (10, 0)!"*
  - *"Created lattice defects with a rate of 0.2 successfully!"*
- Each was classified by whether it mutates the cell, only reads it, or never
  touches it. The **24** that never touch it now refuse. Seven that genuinely
  do work were left alone after reading each one — `buildWulffButton`
  (`removeAtom`), `startSqsButton`/`startCoreHoleButton` (`setName`),
  `applyMagneticButton` (`setProperty("starting_magnetization", …)`),
  `deformCellButton`/`applyPressureButton`/`vacuumButton` (`moveLattice`).
- Modeller totals across both passes: **66 buttons** now refuse honestly.

### Fixed: the Bader button claimed an analysis was running

- Clicking **Bader Analysis** reported *"Analysis Module Started"* and
  *"Bader charge analysis is calculating oxidation states from valence charge
  density..."* while doing nothing. There is no Bader implementation anywhere
  in the tree — no charge-density partitioning, no Bader volume integration,
  no oxidation-state output. The only two references to Bader are this button
  and its registration.
- The present-progressive wording made this worse than a plain false claim: it
  implied a background computation, so a user would *wait* for a result that
  was never coming, then hunt for files that were never written.
- It now refuses through the capability registry and points at the real route
  (run a Bader code on a `pp.x` charge-density CUBE).
- **The guard added with the modeller fix did not catch this**, because it only
  inspected dialogs written inline in a `setOnAction` lambda and this one was a
  named `onIconClicked()` method. The check now also covers click-entry methods
  by name. Message helpers (`showInfo`/`showError`) are excluded — displaying
  text passed in by a caller that did the work is the legitimate case.

### Fixed: 42 modeller buttons announced success without doing anything

- Forty-two controls in the structure modeller opened an **INFORMATION**
  dialog claiming work had completed, while the handler body contained
  *nothing but the dialog*. No cell was read, nothing computed, nothing
  written. Examples, verbatim:
  - "Super Lattice built successfully based on selected input parameters!"
  - "Anharmonic phonon lifetime sweeps and lattice thermal conductivity (κ_L)
    calculations complete! Anharmonic scattering matrices and thermal
    transport relaxation times successfully resolved."
  - "Magnetic Skyrmion Lattice (SkL) array constructed successfully!"
  - "Symmetry vectors refined successfully!"
- The capability registry already classified these as `ADVANCED_SCIENCE`
  **UNAVAILABLE** — only the GUI was claiming otherwise. Every one of them now
  routes through a single `showNotImplemented()` helper that is a **WARNING**,
  states plainly that the control previously reported success without
  computing anything, and quotes the registry entry so the message cannot
  drift from the declared status.
- This is the P0-5/P0-6 fabricated-result defect, and it is worse than a
  crash: a user can spend a long time looking for output that never existed —
  or cite it.
- **New guard** in `scripts/static_checks.py` rejects any handler whose entire
  body is an INFORMATION/CONFIRMATION dialog. Refusal dialogs (WARNING/ERROR)
  are explicitly allowed, because saying "not implemented" is the honest case.
  Two genuinely informational handlers (a static help checklist and the
  capability-status matrix) are a documented baseline. The guard found one
  instance my own bulk edit had missed, and was verified to fire on a
  deliberately reintroduced regression.

### Fixed: spin-polarised PDOS was integrated at exactly twice its true value

- `projwfc.x` writes several column layouts, and the parser assumed one of
  them: energy at column 0, LDOS at column 1, projections from column 2 on.
  That is only correct for a **spin-unpolarised** file:

  ```
  spin-unpolarised   # E (eV)  ldos(E)  pdos(E) ...
  spin-polarised     # E (eV)  ldosup(E) ldosdw(E)  pdosup(E) pdosdw(E) ...
  k-resolved         # ik  E (eV)  ldos(E)  pdos(E) ...
  ```

- A spin-polarised file has **two** LDOS columns, so "everything from column 2"
  folded `ldosdw` — a *local* DOS, itself already the sum over m of the down
  projections — into the projected total. `∫PDOS dE` came out exactly **2×**
  too large. That is the dangerous kind of wrong: a doubled electron count
  still looks plausible on inspection. With `kresolveddos=.true.` the energy is
  not in column 0 at all, so the `ik` index was read as the energy.
- Columns are now located **by name from the file's own header**, which handles
  the spin-polarised, k-resolved, non-collinear and abbreviated forms alike. A
  header with no projection column (LDOS only) yields nothing rather than
  reporting a local DOS as an orbital projection, and a row narrower than its
  own header is refused rather than padded with guesses.
- Affects both consumers: the "Projected DOS inspection" viewer tool and the
  `PDOS_INSPECT` analysis.

### Fixed: `bands.dat` was parsed as if it were the `.gnu` sidecar

- **A gapped insulator could be reported as a metal.** `bands.x` writes *both*
  `filband` (e.g. `bands.dat`) and `filband.gnu`, and the analysis accepts
  either. Only the `.gnu` sidecar is the two-column, blank-line-separated
  layout the parser assumed; `filband` is a `&plot` header, then a k-vector
  line and an energy line per k-point.
- On `filband` this did not merely lose data, it **fabricated a band**. A
  k-vector line has 3 columns and an energy line up to 10, so read as
  `(k, energy)` pairs the energy rows were rejected as "non-monotonic" and the
  surviving k-vector rows produced a curve whose energy is always `k(2)` —
  **0.0** for any path along a symmetry direction. After Fermi referencing that
  is a single perfectly flat band at `-E_F`: a metal. The report was returned
  with `success = true`.
- Both layouts are now detected and parsed. Band *i* is energy *i* of every
  k-point (a transposition of how the file is stored), energies wrapped across
  lines stay one k-point, and the path coordinate accumulates as `plotband.x`
  computes it. A truncated file, a `****` overflow, or a count disagreeing with
  the `&plot` header reports **no** bands rather than invented ones.
- This also unblocks the band-gap and Fermi-review analyses, which share this
  parser and previously failed with "no band curve was parsed" on a `filband`
  file.

### Fixed: `matdyn.freq` was parsed as if it were the `.gp` sidecar

- **A dynamically unstable structure could be reported as stable.** `matdyn.x`
  writes the same frequencies in two layouts. The `.gp` sidecar is one row per
  q-point; the *default* file (`flfrq`, named `matdyn.freq`) is a `&plot`
  header, then a q-vector line followed by the `3*nat` frequencies wrapped six
  per line. The parser assumed the `.gp` shape for both, so on `matdyn.freq`
  every frequency line was discarded as having an "inconsistent branch count"
  (a q line has 3–4 columns, a frequency line up to 6) and the surviving
  **q-vector components were read as the frequencies**.
- This failed in the dangerous direction: q components are small and mostly
  non-negative, so the imaginary-mode test found nothing. A file whose first
  mode is −95 cm⁻¹ returned `isLatticeStable() == true`. Because
  `matdyn.freq` is `matdyn.x`'s own default filename, the broken path was the
  default one.
- Both layouts are now detected and parsed: frequencies wrapped across lines
  are **one** q-point (a 4-atom cell reports 12 branches, not 6); the 4th
  q-column written by current QE is the *weight*, not a frequency; values are
  matched as Fortran reals, since `6f10.4` runs adjacent fields together
  (`-1234.5678-1234.5678`) when one fills its column.
- **Fails closed.** A truncated file, a `****` field overflow, or a count that
  disagrees with the `&plot` header now yields *no verdict* instead of a
  partial "stable" one. No data never reads as "stable".
- The Gamma-point **acoustic sum rule** check had the same root cause plus a
  regex that matched neither real file — it looked for the literal `0.0000000`
  (seven decimals) where `matdyn` writes `f10.6`, then read the rest of that
  line (the remaining q components) as frequencies. It now delegates to the
  frequency parser, locates Gamma **by q vector** so an X–Γ–L path is scored at
  Γ rather than at X, and takes drift by magnitude so a −30 cm⁻¹ acoustic mode
  cannot pass.
- A `ph.x` log handed to either class (the Born/dielectric analysis shares one
  source file) is now rejected instead of having a stability verdict invented
  from its dielectric tensor, and that report no longer prints "sum rule
  satisfied: false" for a check that never ran.
- Frequencies are unchanged for the `.gp` sidecar; verdicts change only where
  they were previously derived from misread columns.

### Testable dialogs: the UserPrompt seam

- **New `UserPrompt` seam** (review item C3). Almost nothing in `app/` was
  unit-testable because dialogs are built inline — ~150 `new Alert(...)` sites,
  18 in `ViewerActions` alone — so "did the export succeed?", "was the user
  warned before the destructive step?" could only be checked by a human
  clicking through the app. `JavaFxUserPrompt` reproduces the existing
  behaviour exactly (same alert types, owner, blocking `showAndWait`), so
  routing a call site through it is a refactor, not a behaviour change.
- `RecordingUserPrompt` captures what *would* have been shown and lets a test
  script answers in advance. Its defaults are **fail-closed**: an unscripted
  `confirm()` returns false and `choose()` returns empty, so a test that
  forgets to script a response exercises the *cancel* path rather than silently
  approving a destructive action.
- **`ExportFormatChooser` extracted** from `ViewerActions.actionExport` (C2
  slice): format-from-filename was pure logic wedged between a `FileChooser`
  and two `Alert`s, so verifying it meant clicking Export once per format. Now
  a table of cases, including the ones easy to get wrong — uppercase
  extensions, names with **no** extension (POSCAR/CONTCAR carry none, which is
  why that is the default), and a dot in a *directory* name:
  `/home/user/run.xyz/POSCAR` must export as POSCAR, not XYZ. The export
  message now also names the format used.
- **`ViewerActions` routed through the seam**: inline `new Alert(...)` sites
  went from 17 to 1 (the last is `static`, so it has no instance seam to use).
  The seven `showX` helpers, the workflow export, XCrySDen launch, final-geometry
  preview, auxiliary-deck builder and the QE-input validation report now go
  through `UserPrompt`, which means the surrounding logic can be exercised
  headless. Long output (validation issues, PDOS/phonon/Raman tables, log
  diagnosis) uses `report()` — a scrollable text area — instead of an `Alert`
  whose label silently truncates.
- The `compile_check` guard protecting the user-pinned audit-version picker
  pinned the JavaFX **class name**, which would have forbidden this refactor
  while proving nothing. It now checks the **behaviour**: that the full mined
  version list is what's offered and that cancelling audits nothing. Verified
  by deliberately reintroducing three regressions (silent newest-version
  default, missing cancel guard, options narrowed to a hardcoded list) and
  confirming the guard fires on each.

### Structure sanity checks before an expensive run

- **New pre-run structure check** (`StructureSanityCheck`, reachable from the
  QE+ tab): overlapping atoms, degenerate cells, lattice edges below 0.5 Å or
  above 500 Å (the classic wrong-unit mistakes), unrecognised species, and
  implausible atom density. These are the failures that cost the most CPU time
  — invisible on screen, harmless to the deck writer, fatal hours later.
- The overlap threshold is the larger of 0.3 Å and half the sum of the two
  covalent radii, **validated against real chemistry first**: the shortest
  ordinary bond (H–H at 0.74 Å) sits well clear of its 0.31 Å limit, as do
  Si–Si, C–C, C–O and Fe–Fe. A checker that cries wolf on ordinary bonds is
  worse than none, so that is the first thing the tests assert.
- Severity is graded honestly: a very large box is a **warning** (legitimate
  for a slab or isolated molecule) and a sparse cell only **info**, while an
  overlap or unusable species is an **error**. The clean result states
  explicitly that this is a sanity check only — it does not verify that the
  structure is the one you meant, that it is relaxed, or that anything is
  converged.
- Detects the **dummy element**: `Atom`'s constructor normalises an
  unrecognised label to the placeholder `X`, so a mislabelled species in a CIF
  silently becomes a structure of dummy atoms that no pseudopotential can be
  assigned to. That is now caught and explained.

### FXML binding checks and workflow recipes where you need them

- **FXML ↔ controller bindings are verified offline.** The UI layer had no
  automated coverage, so a renamed `fx:id` was only found by clicking through
  the app. `static_checks.py` now checks both directions: an `@FXML` field with
  no matching `fx:id` (null after load → NPE on first use) and an `fx:id` with
  no field (dead markup). A rename is reported from both sides at once. This is
  the bug class TestFX targets, caught with no new dependency and no display.
  Pre-existing findings are frozen as baselines — each was inspected, and all
  five unbound-field cases are null-guarded leftovers from removed controls,
  **not** live NPEs.
- **Workflow recipes moved to where they help.** The six curated QE workflows
  (scf, relax, vc-relax, bands, DOS, Γ-phonons) with their prerequisites and
  pitfalls were only reachable from a *post-run* analysis report — after the
  point of use. They are now a section of the QE+ tab. Deliberately guidance,
  not one-click generators: filling in cutoffs and meshes would assert
  convergence parameters that depend on your material.

### Unit handling: one derivation instead of pasted literals

- **Ry→meV is now derived from the shared unit layer.** Three values for one
  constant existed in code that decides whether a convergence sweep has
  finished: `ConvergenceSweepRunner` had `13605.693`, `OccupationAdvisor` had
  `13605.693122994`, and `Constants.RYTOEV` derives `13605.691930…`. Both
  literals now go through `Unit.convert()`.
- The typed layer (`com.units.Unit`) already existed and was dimension-checked
  — it throws if you convert an energy to a length — but had only one consumer.
  Its javadoc now states **which of the two constant families to use when**:
  `Constants.*` (the 2006-era values Quantum ESPRESSO itself ships) when a
  number must agree with `pw.x`, `QEUnits.*` (CODATA-2018) when reporting to the
  user. They differ at the `1e-8` relative level — far below any meaningful
  threshold, so this is a maintainability fix, **not** a numerical bug fix.
- `static_checks.py` now **rejects new hardcoded conversion literals**, with the
  existing ones frozen as a per-file baseline so the check cannot silently grow.
  Verified to fail on a literal added to a clean file and pass once removed.

### Symmetry in the Band tab, and tools moved to where they apply

- **spglib/seekpath is now reachable from the GUI** (`SymmetryAdvisor`). The
  backend already existed and nothing used it, while the Band tab derived its
  high-symmetry labels from `ibrav` **alone** — which cannot be right in
  general, because the Bravais lattice ignores the atomic basis (diamond and
  zincblende share an `ibrav` but not a space group or a correct path). The
  Band tab gained a **"Detect space group / band path"** control that reports
  the group from the *structure* and offers to apply the standard path for it.
  Fail-closed: with no sidecar it says what to install and changes nothing —
  it never falls back to the `ibrav` guess. Reports always quote the tolerance,
  because a space group is only meaningful together with one.
- **Tools redistributed to where they apply** (item 27). "Validate QE input"
  and "Auxiliary deck builder" act on the QE deck, so they moved from the
  workspace menu — where they were offered even under VASP — to the QE+ tab.
  Structure actions ("Open in XCrySDen", "Export structure", "Screen-shot",
  "Modeler", "Designer") are now also available by **right-clicking the
  viewer**; they remain in the menu, so no habit breaks. What stays in the
  bottom-left menu is calculator-agnostic: view, save, run, result, export and
  the Change-calculator pop-up. Nothing is duplicated — every relocated button
  dispatches the same action, and a test pins that relocated tools stay
  registered so none becomes a dead button.

### Honesty: generated capability matrix, quarantined prototypes, run-state badge

- **The capability matrix is generated from the code.** `CapabilityRegistry`
  gains `createMarkdownMatrix()`, exposed as `quantumforge --capability-matrix`,
  and `scripts/generate_capability_matrix.py` rewrites the README block between
  explicit markers. `static_checks.py` fails the build when the README is stale,
  so the docs cannot drift. This was overdue: the hand-written table called
  SSH/HPC "Unavailable" and Symmetry a "Bravais-metric helper only" while the
  registry recorded both as **Partial** with real machinery behind them, and its
  header still read "Status in 2.0.0" at version 2.0.9.
- **Prototypes are hidden unless `--experimental` is passed.** `SUPPORTED` and
  `PARTIAL` surfaces stay visible; `EXPERIMENTAL` and `UNAVAILABLE` require the
  opt-in, and an unregistered surface **fails closed** (hidden), so adding a
  prototype without declaring its maturity cannot ship an unbacked claim.
- **Two surfaces that reported success while doing nothing now fail closed**:
  "Jupyter Lab" showed *Upload Successful* without transferring anything, and
  "Grand-project" asked for a type and a destination directory before reporting
  *Export Successful* without writing a file. Both are registered `UNAVAILABLE`,
  hidden by default, and explain what is missing.
- **Drafted / executed / parsed badge** (`EngineRunState`): the engine editors
  now show, with a timestamp, whether input was only *drafted*, the engine
  *executed*, its output *parsed*, or the run *failed* — because a formatted
  INCAR looks identical whether VASP ran or not. Per-session and in-memory by
  design: inferring "executed" from a leftover `vasprun.xml` would credit this
  workspace with someone else's run. "Parsed" is claimed only when the engine
  result actually reports success.

### Scientific guardrails, golden fixtures, run provenance

- **Golden QE fixtures** (`tests/fixtures/qe/golden`): five `.in`/`.out`/`.expect`
  triples — Si 2-atom, MgO insulator, spin-polarised Fe, a slab with ~26 Å
  vacuum, and DFT+U via the QE 7.x `HUBBARD` card. `QeGoldenFixtureTest` asserts
  **both** directions: the deck is parsed *and* re-serialised/re-parsed against
  the same expectations (so a writer that drops a keyword fails), and the output
  is parsed by the production analyzers. `PROVENANCE.md` states plainly that
  these are format-faithful to QE 7.5 but **not yet captured from a real `pw.x`
  run**, and documents the data-only steps to replace them with real output.
  `scripts/fixture_harness.py` validates the invariants offline in CI.
- **Cutoffs come from the pseudopotentials** (`PseudoCutoffAdvisor`): reads each
  UPF's own `wfc_cutoff`/`rho_cutoff` and its type — both already parsed but
  previously discarded — and takes the **maximum** across species. Targets the
  mixed NC + ultrasoft set silently run at the NC ×4 dual. The Convergence tab
  defaults to "From pseudopotentials" and highlights a start below requirement.
- **k-mesh from the cell metric** (`KMeshAdvisor`): derives the mesh from a
  target spacing in Å⁻¹ and pins a detected vacuum axis to exactly one k-point.
  Complements the existing `QEKpointMeshAdvisor`, which grades a mesh you have.
- **Occupation guardrails** (`OccupationAdvisor`): flags fixed occupations on a
  metal, wide smearing on an insulator, smearing without a width, and an odd
  electron count without spin. A small-gap system is reported as *undetermined*
  rather than guessed. Surfaces that the `!` line is the free energy `F = E − TS`.
- **Convergence records which observable converged**: `.quantumforge.convergence.json`
  is schema v2 with the observable, unit, criterion and an explicit caveat that
  phonons/elastic constants/gaps converge later than the energy. Additive — v1
  files still load — and the viewer labels axes from the record instead of
  assuming "Total Energy".
- **QE run provenance**: `RunManifest` gains MPI rank count and per-element
  pseudopotential identity (name + SHA-256). Schema v2, all v1 fields unchanged.
- **Calculator/tab memory**: the calculator is remembered per workspace
  (persisted) and the tab per calculator (session), so reopening a VASP
  workspace lands on VASP and switching engines and back returns to your tab.
- **Run is blocked on unsaved edits**: `isProjectSaved()` only checked the
  directory existed, so a run could use the *previous* on-disk deck while the
  editor showed the new one. It now also requires no unsaved changes.
- **Fixed**: an illegal multi-catch (`IllegalArgumentException | RuntimeException`)
  broke the build; `scripts/compile_check.py` now detects that error class
  offline. Every fan-menu tab now always has an action, so a tab whose editor
  failed to build explains itself instead of appearing frozen.

### Calculator pop-up, per-engine tabs, QE+ tab, live input-file refresh

- **New "Change calculator" pop-up** (`QEFXCalculatorDialog`), separate from the
  bottom-right fan menu. It lists every calculator - Quantum ESPRESSO, VASP,
  `thermo_pw`, BoltzTraP2, phonopy / phono3py, CASTEP, XCrySDen - with a
  description and a live executable-availability line resolved from "Path of
  Software". It is opened from the bottom-left calculator badge (now clickable)
  or the viewer menu's "Change calculator". Engines without a configured
  executable stay selectable for input drafting, and the row says so rather
  than implying the code is installed.
- **The fan menu is now a within-calculator tab switcher.** It lists only the
  active calculator's tabs (`CalculatorTabs`): for QE the ten calculation tabs
  plus QE+ and Post-run Analysis; for an external engine its setup tab (e.g.
  "VASP Setup") plus its own Post-run Analysis tab. The engines no longer sit
  in the fan menu next to SCF/DOS/Band, and QE's tabs no longer leak into an
  external engine. The badge now shows the active *calculator*, not the tab.
- **New QE+ tab.** The Quantum ESPRESSO grammar version and the locked
  `prefix` / `pseudo_dir` / `outdir` environment moved out of the "Path of
  Software" dialog (where they sat among unrelated executable paths) into the QE
  calculator itself, persisted through the same `QEVersion` /
  `QEEnvironmentPaths` single sources of truth. The dialog keeps the paths and
  the run command, and points at the new location.
- **Post-run Analysis now exists for every calculator**, listing the tools that
  can actually read that engine's output (`EngineAnalysisTools`): QE keeps its
  eight tools; BoltzTraP2 gets the transport chart and studio; phonopy the
  band/DOS studio; `thermo_pw` the live monitor and ELATE; XCrySDen its
  launcher; VASP and CASTEP get a direct `vasprun.xml` / `.castep` parse. Each
  button dispatches the same viewer action as before - no analysis logic is
  duplicated. Those engine-specific tools left the bottom-left teeth menu.
- **Analysis and engine editors now match the standard tab width.** The
  Post-run Analysis panel and the calculator editors are pinned to the same
  425px editor column the FXML tabs (SCF, Optimize, DOS, ...) use; the engine
  editor's action row became a file selector above a wrapping button bar, which
  is what used to force the right-hand pane much wider than every other tab.

### Fixes

- **The input-file popup now follows the tab immediately.** Switching between
  calculators or tabs (e.g. VASP to QE) no longer requires a reload or a
  close/reopen. `Project.onInputModeChanged` was insufficient: tabs without a QE
  input mode never fired it, and when it did fire it arrived *before* the active
  tab name was updated, so the popup rebuilt from the previous tab. A new
  `EditorTabChanged` callback fires after both the tab name and the active
  engine are applied, and the popup rebuilds on the FX thread. Its header also
  names the calculator and tab being shown, and QE+/Post-run Analysis state
  plainly that they have no input deck instead of leaving a stale one visible.
- **The Convergence tab (and any tab) can no longer leave the workspace greyed
  out.** Opening a menu disables the project pane and selecting an item
  re-enables it, but the re-enable ran only if the selected action returned
  normally - any exception while switching tab skipped it and left every control
  unclickable. Both menus now re-enable in a `finally` block and log the
  failure. Additionally `Project.setInputMode` iterates a copy of its listeners
  and isolates listener failures, and the Convergence refresh steps are
  individually guarded, so a not-yet-loaded pseudopotential library degrades to
  a message instead of an inert panel.
- The Convergence status banner distinguishes "PP library still loading" from
  "no pseudopotentials for these elements", and notes that the cutoff and
  k-point sweeps do not need the library (new `PseudoLibrary.isLibraryLoaded`).
- The input-file popup resolved the active engine from a *file name* rather than
  the active tab, so a single-file calculator's deck (e.g. BoltzTraP2
  `boltz.intrans`) was not recognised as editable and "upload" silently did
  nothing.
- The VASP/CASTEP analysis output now renders through `EngineResult.summaryText()`,
  which includes the parsed scalars (final energy, forces, stress, run time) and
  the provenance block.

### Live calculator values, real convergence sweep, configurable paths

- Live values in input-file tabs: the external calculator editors publish their
  live field values (`CalculatorLiveValues`), and the input-file popup renders
  the multi-file tabs from them (`CalculatorFiles`), so the preview reflects
  what the user typed, not schema defaults.
- Per-calculator file switcher: each external calculator editor has a "File:"
  selector (VASP INCAR/POSCAR/KPOINTS/POTCAR, phonopy conf/band.conf/SPOSCAR,
  thermo_pw.in, CASTEP param/cell, ...) so you switch between a calculator's
  input files directly; Show/Copy target the selected file.
- Real convergence sweep: `ConvergenceSweepRunner` runs `pw.x` per rung
  (ecutwfc with coupled ecutrho, or the k-mesh), parses the final total energy,
  auto-stops on |ΔE|/atom below the criterion, and writes the real
  `.quantumforge.convergence.json` the fail-closed viewer reads. Fails closed if
  `pw.x` is unconfigured or a rung yields no energy. The "Run Convergence Test"
  button now launches this with a live progress dialog.
- prefix/outdir are user-configurable-but-locked: editable only in the "Path of
  Software" dialog (persisted via `QEEnvironmentPaths`/`Environments`), read-only
  everywhere else; pseudo_dir follows the PP library path.
- Inheritance preserves DOS/Band `nbnd` and k-points (they often need more bands
  / a denser mesh than the SCF); all other `&system` keywords still inherit.
- Docs: `CODE_AUDIT.md`, `SCIENTIFIC_SOFTWARE_GUIDE.md`, and the README
  capability matrix now state that the external engines live in the "Change
  calculator" fan menu as review-only drafters and that convergence is a real
  sweep with a fail-closed viewer (no fabricated data).

### Cross-tab inheritance & single source of truth (#1, #3)

- Cross-tab keyword inheritance: the SCF deck now owns the `&system` setup
  (structure, ecutwfc/ecutrho, occupations/smearing/degauss, spin, lda_plus_u,
  input_dft, vdw_corr, nbnd, tot_charge, nosym). After every resolve,
  `ProjectBody.inheritSharedSetupFromScf()` copies it into the Optimize / MD /
  DOS / Band decks and the Convergence copy, so editing such a keyword in the
  SCF tab auto-applies to every other tab (SCF wins; mode-specific namelists
  `&control`/`&electrons`/`&ions`/`&cell` are untouched).
- Globally locked `prefix`/`pseudo_dir`/`outdir` via a new single source of
  truth `QEEnvironmentPaths` (prefix `espresso`, outdir `./out/`, pseudo_dir
  from the configured library). The base `QEInputCorrecter` writes them into
  every pw.x deck so all calculators share one prefix; they are exposed
  read-only in the "Path of Software" dialog and no longer edited per-tab.

### Advanced keywords (#2)

- The pw.x Advanced Keywords tab is version-windowed: a QE-version picker
  (7.2-7.6) routes through the same mined grammar catalog used for ph.x/hp.x
  (`QEDeckKeywordCatalog.forVersion(Kind.PW, version)`); catalog-known keywords
  show only for the versions that accept them, while grammar-unknown keywords
  always show.

### Input-file popup (#5, #6)

- The input-file popup is resizable (bottom-right drag grip).
- When a calculation needs more than one input file, each file is shown as a tab
  below the "Input-file" header (single-file calculations keep the plain
  editor): QE DOS (pw scf / pw nscf / dos.x / projwfc.x), QE Band (pw scf /
  pw nscf / bands.x), QE Phonon (pw scf / ph.x / q2r.x / matdyn.x), VASP
  (INCAR / POSCAR / KPOINTS / POTCAR species), thermo_pw (scf.in / thermo_pw.in),
  phonopy (conf / band.conf / SPOSCAR), CASTEP (seed.param / seed.cell),
  BoltzTraP2 (boltz.intrans), XCrySDen (tcl). Reuses `AtomicExporter.toPOSCAR`
  and `CalculatorSchemas.serialize`.

### Calculator menu & analysis tab (#7, #8)

- The external engines (VASP, CASTEP, phonopy, thermo_pw, BoltzTraP2, XCrySDen)
  are reached only from the bottom-right "change calculator" fan menu (the
  computation calculator for the workspace); the viewer "Change calculator" item
  opens that fan menu; the top-level Menu ▸ Extensions no longer duplicates them.
- New last fan-menu tab "Post-run Analysis" aggregates the post-run tools
  (diagnose log, band gap, PDOS, phonons, Raman/IR, density difference, final
  geometry, analyze results) and dispatches the same viewer actions as before;
  those tools were moved out of the bottom-left teeth menu (still actionable).

### Advanced-keyword de-duplication

- Removed already-curated / predefined keywords from the Advanced Keywords
  editors (SCF tab + shared Opt/MD/DOS/NEB/TDDFT section) via a per-tab
  curated-key exclusion set; removed preset paths prefix/pseudo_dir/outdir.

### Integrity (#4)

- The convergence result viewer no longer fabricates/persists simulated
  convergence curves. It only parses a real `.quantumforge.convergence.json`
  (`loadConvergenceData`) and otherwise shows an honest "No convergence run
  found" empty state. Simulated-physics test replaced with fail-closed tests.

### UI / editor cleanup (earlier)

- Moved the external calculation engines (VASP, CASTEP, phonopy / phono3py,
  thermo_pw, BoltzTraP2, XCrySDen) out of the top-level Menu ▸ Extensions list.
  They are now reached only from the project editor's "Change calculator" fan
  menu (the computation calculator for the current workspace); the viewer's
  "Change calculator" item now opens that same fan menu instead of a placeholder
  dialog. The Extensions menu keeps non-engine guides (Phonon Stability Guide).
- De-duplicated the "Advanced Keywords" editors: keywords that already have a
  curated control in the same editor (e.g. `diago_david_ndim`, `mixing_ndim` in
  SCF/Electrons; `ion_dynamics`, `cell_dynamics`, `press`, ... in Optimize/MD;
  `Emin`/`Emax`/`DeltaE`/`ngauss`/`degauss` in DOS) and predefined paths
  (`prefix`, `pseudo_dir`, `outdir`) are no longer repeated. The shared advanced
  section now takes a per-tab set of already-curated keys to skip.
- Convergence editor: added a status banner that states whether a structure and
  pseudopotential library are available and what the planner does, and forces
  the panel's controls to an enabled state so the tab never appears inert.

## 2.0.0 — 2026-07-16

### Release engineering

- Added reproducible Maven/JDK 17/OpenJFX build, modern dependency declarations, JUnit tests, and CycloneDX SBOM.
- Added `quantumforge` launcher with `--version`, `--doctor`, remote-X11 software-rendering fallback, file arguments, and clear Java errors.
- Added platform portable archives, jpackage native packaging, Arch PKGBUILD, safe per-user install/update/uninstall, desktop/PATH integration, and checksum verification.
- Maintained CI/release workflow templates under `packaging/github-workflows/` for Ubuntu 20.04 baseline, Arch, Windows, and Intel/Apple-Silicon macOS (copy into `.github/workflows/` with a token that has `workflows` permission; configure signing secrets before production).
- Added full multi-platform install tutorial (`docs/TUTORIAL_INSTALL.md`) covering safe install/update/uninstall and MobaXterm `quantumforge` GUI launch.
- Added comprehensive installation, external-engine, release-security, code-audit, and 170-item roadmap documentation.

### Project safety and run provenance (roadmap batch 2)

- Atomic project property/input writes via stage+fsync+rename (`AtomicFileWriter`) with last-known-good `.bak` copies.
- Project schema v1 metadata (`schemaVersion`, `quantumforgeVersion`) on status JSON.
- Debounced autosave snapshot helper (`.quantumforge.autosave/`).
- Structured rotating logs with job IDs and secret redaction (`~/.quantumforge/logs/`).
- Local-first crash reporter writing redacted diagnostic bundles (no automatic upload).
- QE executable profile probing in `quantumforge --doctor`.
- Per-stage run manifests (`.quantumforge.run-manifest.jsonl`) with command/hash/exit provenance.
- Process-tree cancellation with QE EXIT file then graceful/forced descendant kill.

### QE reliability foundations (roadmap batch 3)

- Fixed autosave so snapshots export without rebinding the live project directory; dirty-state probe in open projects; recovery list/restore API with pre-restore backup.
- `SecretStore` (memory-default, optional OS-keyring backend) for Materials API keys.
- Immutable `PhysicalQuantity`/`Unit` conversion library (Ry/eV/Ha, bohr/Å, kbar/GPa, cm⁻¹/THz).
- Incremental UTF-8 `LiveFileTailer` integrated into log parsing.
- Deterministic QE error knowledge base consulted after failed jobs.
- SCF convergence analyzer (energy, estimated accuracy, trend) and geometry convergence validator with golden log fixtures.
- Final-geometry typed preview (apply remains fail-closed).
- Maintainer first-release checklist: `docs/FIRST_RELEASE.md`.

### Command DAG, restart, recovery GUI (roadmap batch 4)

- Viewer menu **Recover autosave ...** with snapshot picker and pre-restore backup.
- Typed `QECommandDag` for SCF/relax/MD/DOS/bands pipelines with artifact dependencies and resume filtering.
- `RestartManager` validates `prefix.save` completeness before recommending restart.
- `WorkflowExporter` writes bash/SLURM scripts from the DAG.
- Expanded golden fixtures (Fe spin SCF, bands path, DOS) plus offline fixture/compile harnesses in CI template.
- Fixed SCF/Fermi log parsers to accept Fortran `D` exponents.

### Runner wiring and external tools (roadmap batch 5)

- `RunningNode` dry-run preflight, DAG stage IDs, on-disk artifact stage skipping, auto workflow script export.
- Viewer menus: **Export workflow script**, **Open in XCrySDen** (safe temp XSF + argument-array launch).
- `ArtifactScanner` and `DryRunPreflight` for resume/preflight decisions.
- SCF convergence summary written to structured logs after stages.

### Correctness and safety

- Added one authoritative capability registry exposed by the GUI and `quantumforge --capabilities`; executable detection no longer implies integration support.
- Added deterministic QE preflight for atom/species counts, pseudopotential selection, lattice volume, cutoffs, smearing, SOC/noncollinear consistency, and k-point completeness; invalid jobs are blocked before execution.
- Replaced ambiguous no-op booleans with typed operation results for disabled SSH/SFTP and local scheduler paths while retaining deprecated compatibility wrappers.
- Rebuilt band-gap analysis with rectangular/finite validation, explicit state degeneracy, occupation-aware metallic detection, direct/indirect k-point evidence, and DOS threshold-crossing diagnostics.
- Corrected PDOS integration to use trapezoids on nonuniform energy grids and defensive copies.
- Replaced endpoint diffusivity with least-squares fitting, R², fit window, and standard error; strengthened formation-energy, exciton, CHE, piezoelectric-ratio, and McMillan helper contracts.
- Removed fabricated random/zero/mock outputs from work-function maps, hyperfine, SOC, orbital magnetization, Weyl, STH, volumetric differences, and phonon thermodynamics; those paths now fail explicitly.
- Fixed three `QEInputBinder` bounds checks that used OR instead of AND, a secondary-input type guard, a public `SocksProxyConfig` filename/class mismatch that prevented Java compilation, malformed Modeler FXML nesting, and a Γ-centering path that expected a nonexistent six-element grid.
- Hardened UPF XML parsing against DTD/external-entity access, imposed a 128 MiB limit, and fixed UTF-8 handling.
- Stopped serializing SSH passwords, disabled plaintext proxy-password persistence, and migrates a legacy Materials Project API key to session-only memory.
- Fixed startup failure caused by parsing semantic version `2.0.0` as a Java double.
- Fixed upgrades replacing all user QE paths/settings; migration now preserves user values.
- Stopped automatically persisting nonexistent legacy bundled-QE paths.
- Fixed Γ-centred automatic k-grid offsets.
- Stopped generating invalid pseudo-CPMD, NMR/GIPAW, and XAFS/XSpectra `pw.x` inputs; those incomplete workflows now fail explicitly.
- Stopped fabricating space and magnetic-space groups from lattice metrics.
- Corrected CIF loop/labels, POSCAR species ordering, locale-independent numeric export, element masses, and unsafe guessed QE pseudopotential names/cutoffs.
- Replaced misleading “complete VASP/CASTEP GUI” messages with accurate implementation status.
- Replaced abandoned JSch 0.1.54 with maintained `com.github.mwiede:jsch` and upgraded other declared dependencies.
- Normalized fourteen non-UTF-8 source files and corrected broken/obsolete URLs.

### Known limitations

- SSH/SFTP/scheduler submission contains unresolved TODO/no-op methods and is not production-ready.
- VASP is limited to POSCAR I/O and a disconnected INCAR prototype; CASTEP is not implemented.
- thermo_pw, phonopy, BoltzTraP2 and XCrySDen are not complete end-to-end integrations.
- Advanced physics/catalysis/battery/topology/ML modules include unwired or simplified prototypes and are not validated research features.
- Native Windows/macOS code signing requires owner-provided certificates and protected CI secrets; unsigned artifacts must be labeled accordingly.
- The initial test suite is not yet the required QE multi-version golden-output corpus.

### SSH/HPC and spglib foundations (roadmap batch 6)

- Strict `KnownHostsStore` and `JschSshTransport` (fail-closed host keys; session-only passwords).
- SFTP path guards, unique remote job directories, temp upload+rename pattern.
- `SlurmSchedulerAdapter`, `SiteProfile` loader, `JobRecord` state machine.
- `SSHJob` prepares scripts offline; submit requires a connected transport.
- `SpglibService` + `tools/spglib_sidecar.py` isolated protocol (no invented space groups).
- Example site profile: `packaging/sites/example-slurm.yaml`.

### HPC hardening (roadmap batch 7)

- Interactive host-key acceptance helper wired into remote RunAction.
- Selective result sync via required/optional/large manifests.
- PBS/Torque scheduler adapter; safe cancel-by-id with status verification.
- Remote run path uses typed OperationResult (no silent boolean success).

### HPC reliability (roadmap batch 8)

- SGE/UGE scheduler adapter and example site profile.
- Durable JSONL job queue store for reconstructing remote jobs after restart.
- Selective result sync checksum cache to skip unchanged files.
- Symmetry conversion remains fail-closed even when spglib dataset metadata is available (no silent identity transform).

### Secrets, XML results, symmetry v2, remote monitor (roadmap batch 9)

- Process-based OS keyring backend (`secret-tool` / macOS `security`) with memory fallback.
- XML-first Quantum ESPRESSO `data-file-schema.xml` parser (XXE-hardened) preferred by ScfParser.
- spglib/seekpath sidecar protocol v2: dataset, primitive/conventional standardization, k-path.
- Remote job monitor with exponential backoff and terminal-state detection.

### NEB, checkpoint resubmit, phonon thermo, Windows secrets (roadmap batch 10)

- Fixed NEB lattice interpolation bug and added typed path creation with validation.
- Checkpoint-aware resubmit planner writes explicit restart plans and preserves job history.
- Harmonic phonon-DOS thermodynamic integration replaces fabricated thermo placeholders.
- QE XML parser extracts total force and stress when present.
- Windows DPAPI credential backend for SecretStore.

### NEB/phonon workflows and richer XML/resubmit (roadmap batch 11)

- Added `RunningType.NEB` and `RunningType.PHONON` command lists, DAG stages, logs/errors/parsers/post hooks.
- Registered `neb.x`/`ph.x`/`q2r.x`/`matdyn.x` command types and properties.
- QE XML parser now extracts per-atom force vectors.
- Checkpoint resubmit can export an executable local restart script.
- Result-sync manifests include NEB/phonon artifacts.
