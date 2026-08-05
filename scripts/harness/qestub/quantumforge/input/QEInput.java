/*
 * HARNESS-ONLY structural stub (never compiled into the application jar).
 *
 * The real quantumforge.input.QEInput is transitively coupled to the JavaFX
 * 3D scene graph through atoms.model.Cell/Atom, so the headless javac harness
 * cannot compile it. This stub reproduces ONLY the namelist surface the
 * schema adapter (QESchemaValidator) and its tests exercise:
 *   - the eight NAMELIST_* constants and listNamelistKeys()
 *   - the protected namelists map and getNamelist(String)
 * Cards, readers, correcters and molecule/cell builders are out of scope here.
 */
package quantumforge.input;

import java.util.LinkedHashMap;
import java.util.Map;

import quantumforge.input.namelist.QENamelist;

public abstract class QEInput {

    public static final String NAMELIST_CONTROL = "CONTROL";
    public static final String NAMELIST_SYSTEM = "SYSTEM";
    public static final String NAMELIST_ELECTRONS = "ELECTRONS";
    public static final String NAMELIST_IONS = "IONS";
    public static final String NAMELIST_CELL = "CELL";
    public static final String NAMELIST_DOS = "DOS";
    public static final String NAMELIST_PROJWFC = "PROJWFC";
    public static final String NAMELIST_BANDS = "BANDS";
    // Roadmap R1 mirror: pw.x extension decks (&FCP/&RISM/&WANNIER/&WANNIER_AC/
    // &PRESS_AI) - read-side audit surfaces only, the write path is untouched.
    public static final String NAMELIST_FCP = "FCP";
    public static final String NAMELIST_RISM = "RISM";
    public static final String NAMELIST_WANNIER = "WANNIER";
    public static final String NAMELIST_WANNIER_AC = "WANNIER_AC";
    public static final String NAMELIST_PRESS_AI = "PRESS_AI";

    public static String[] listExtraNamelistKeys() {
        return new String[] {
                NAMELIST_FCP,
                NAMELIST_RISM,
                NAMELIST_WANNIER,
                NAMELIST_WANNIER_AC,
                NAMELIST_PRESS_AI
        };
    }

    public static String[] listAllNamelistKeys() {
        String[] primary = listNamelistKeys();
        String[] extra = listExtraNamelistKeys();
        String[] all = new String[primary.length + extra.length];
        System.arraycopy(primary, 0, all, 0, primary.length);
        System.arraycopy(extra, 0, all, primary.length, extra.length);
        return all;
    }

    public static String[] listNamelistKeys() {
        return new String[] {
                NAMELIST_CONTROL,
                NAMELIST_SYSTEM,
                NAMELIST_ELECTRONS,
                NAMELIST_IONS,
                NAMELIST_CELL,
                NAMELIST_DOS,
                NAMELIST_PROJWFC,
                NAMELIST_BANDS
        };
    }

    protected Map<String, QENamelist> namelists = new LinkedHashMap<>();

    public QENamelist getNamelist(String key) {
        if (!this.namelists.containsKey(key)) {
            return null;
        }
        return this.namelists.get(key);
    }

    public abstract void reload();
}
