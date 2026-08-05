/*
 * HARNESS-ONLY structural stub (never compiled into the application jar).
 *
 * Mirrors the real QESCFInput namelist surface: a fresh SCF input carries
 * exactly the CONTROL, SYSTEM and ELECTRONS namelists (IONS/CELL arrive only
 * in relax/md input subclasses); tracers, cards and correcters are pruned.
 */
package quantumforge.input;

import quantumforge.input.namelist.QENamelist;

public class QESCFInput extends QEInput {

    public QESCFInput() {
        this.namelists.put(NAMELIST_CONTROL, new QENamelist(NAMELIST_CONTROL));
        this.namelists.put(NAMELIST_SYSTEM, new QENamelist(NAMELIST_SYSTEM));
        this.namelists.put(NAMELIST_ELECTRONS, new QENamelist(NAMELIST_ELECTRONS));
    }

    @Override
    public void reload() {
        // no-op in the harness stub
    }
}
