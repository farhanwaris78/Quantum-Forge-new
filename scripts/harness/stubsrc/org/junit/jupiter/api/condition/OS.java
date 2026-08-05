package org.junit.jupiter.api.condition;
public enum OS {
    LINUX, MAC, WINDOWS, SOLARIS, AIX, OTHER;
    public static OS current() {
        String name = System.getProperty("os.name", "").toLowerCase(java.util.Locale.ROOT);
        if (name.contains("windows")) return WINDOWS;
        if (name.contains("mac") || name.contains("darwin")) return MAC;
        if (name.contains("linux")) return LINUX;
        if (name.contains("sunos") || name.contains("solaris")) return SOLARIS;
        if (name.contains("aix")) return AIX;
        return OTHER;
    }
    public boolean isCurrentOs() { return this == current(); }
}
