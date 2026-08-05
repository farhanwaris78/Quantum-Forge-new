package org.junit.jupiter.api;

import java.util.Objects;
import java.util.function.Supplier;

import org.junit.jupiter.api.function.Executable;
import org.junit.jupiter.api.function.ThrowingSupplier;

/**
 * Minimal harness re-implementation of the JUnit 5 Assertions surface used by
 * the QuantumForge test suites. Semantics mirror JUnit: equality via equals,
 * exact double/float compare unless a delta is given, message lazily supplied.
 */
public final class Assertions {

    private Assertions() {
    }

    private static String msg(String message, Supplier<String> supplier) {
        if (message != null) {
            return message;
        }
        return supplier == null ? null : supplier.get();
    }

    private static void failWith(String message) {
        throw new AssertionError(message == null ? "assertion failed" : message);
    }

    public static void fail() {
        failWith(null);
    }

    public static void fail(String message) {
        failWith(message);
    }

    public static void assertTrue(boolean condition) {
        if (!condition) {
            failWith("expected: <true> but was: <false>");
        }
    }

    public static void assertTrue(boolean condition, String message) {
        if (!condition) {
            failWith(message);
        }
    }

    public static void assertTrue(boolean condition, Supplier<String> messageSupplier) {
        if (!condition) {
            failWith(msg(null, messageSupplier));
        }
    }

    public static void assertFalse(boolean condition) {
        if (condition) {
            failWith("expected: <false> but was: <true>");
        }
    }

    public static void assertFalse(boolean condition, String message) {
        if (condition) {
            failWith(message);
        }
    }

    public static void assertFalse(boolean condition, Supplier<String> messageSupplier) {
        if (condition) {
            failWith(msg(null, messageSupplier));
        }
    }

    public static void assertNull(Object actual) {
        if (actual != null) {
            failWith("expected: <null> but was: <" + actual + ">");
        }
    }

    public static void assertNull(Object actual, String message) {
        if (actual != null) {
            failWith(message);
        }
    }

    public static void assertNull(Object actual, Supplier<String> messageSupplier) {
        if (actual != null) {
            failWith(msg(null, messageSupplier));
        }
    }

    public static void assertNotNull(Object actual) {
        if (actual == null) {
            failWith("expected: not <null>");
        }
    }

    public static void assertNotNull(Object actual, String message) {
        if (actual == null) {
            failWith(message);
        }
    }

    public static void assertNotNull(Object actual, Supplier<String> messageSupplier) {
        if (actual == null) {
            failWith(msg(null, messageSupplier));
        }
    }

    public static void assertEquals(int expected, int actual) {
        if (expected != actual) {
            failWith("expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(int expected, int actual, String message) {
        if (expected != actual) {
            failWith(msg(message, null) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(int expected, int actual, Supplier<String> messageSupplier) {
        if (expected != actual) {
            failWith(msg(null, messageSupplier) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(long expected, long actual) {
        if (expected != actual) {
            failWith("expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(long expected, long actual, String message) {
        if (expected != actual) {
            failWith(msg(message, null) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(long expected, long actual, Supplier<String> messageSupplier) {
        if (expected != actual) {
            failWith(msg(null, messageSupplier) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(double expected, double actual, double delta) {
        if (Double.isNaN(expected) && Double.isNaN(actual)) {
            return;
        }
        if (Math.abs(expected - actual) > delta) {
            failWith("expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(double expected, double actual, double delta, String message) {
        if (Double.isNaN(expected) && Double.isNaN(actual)) {
            return;
        }
        if (Math.abs(expected - actual) > delta) {
            failWith(msg(message, null) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(double expected, double actual, double delta,
            Supplier<String> messageSupplier) {
        if (Double.isNaN(expected) && Double.isNaN(actual)) {
            return;
        }
        if (Math.abs(expected - actual) > delta) {
            failWith(msg(null, messageSupplier) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(float expected, float actual, float delta) {
        if (Float.isNaN(expected) && Float.isNaN(actual)) {
            return;
        }
        if (Math.abs(expected - actual) > delta) {
            failWith("expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(float expected, float actual, float delta, String message) {
        if (Float.isNaN(expected) && Float.isNaN(actual)) {
            return;
        }
        if (Math.abs(expected - actual) > delta) {
            failWith(msg(message, null) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(Object expected, Object actual) {
        if (!Objects.equals(expected, actual)) {
            failWith("expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(Object expected, Object actual, String message) {
        if (!Objects.equals(expected, actual)) {
            failWith(msg(message, null) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertEquals(Object expected, Object actual, Supplier<String> messageSupplier) {
        if (!Objects.equals(expected, actual)) {
            failWith(msg(null, messageSupplier) + " ==> expected: <" + expected + "> but was: <" + actual + ">");
        }
    }

    public static void assertNotEquals(Object unexpected, Object actual) {
        if (Objects.equals(unexpected, actual)) {
            failWith("expected values to differ, both were: <" + actual + ">");
        }
    }

    public static void assertNotEquals(Object unexpected, Object actual, String message) {
        if (Objects.equals(unexpected, actual)) {
            failWith(message);
        }
    }

    public static void assertSame(Object expected, Object actual) {
        if (expected != actual) {
            failWith("expected same instance");
        }
    }

    public static void assertSame(Object expected, Object actual, String message) {
        if (expected != actual) {
            failWith(message);
        }
    }

    public static void assertNotSame(Object unexpected, Object actual) {
        if (unexpected == actual) {
            failWith("expected different instances");
        }
    }

    public static void assertNotSame(Object unexpected, Object actual, String message) {
        if (unexpected == actual) {
            failWith(message);
        }
    }

    public static void assertArrayEquals(int[] expected, int[] actual) {
        if (!java.util.Arrays.equals(expected, actual)) {
            failWith("array contents differ");
        }
    }

    public static void assertArrayEquals(int[] expected, int[] actual, String message) {
        if (!java.util.Arrays.equals(expected, actual)) {
            failWith(message + " ==> array contents differ");
        }
    }

    public static void assertArrayEquals(byte[] expected, byte[] actual) {
        if (!java.util.Arrays.equals(expected, actual)) {
            failWith("array contents differ");
        }
    }

    public static void assertArrayEquals(byte[] expected, byte[] actual, String message) {
        if (!java.util.Arrays.equals(expected, actual)) {
            failWith(message + " ==> array contents differ");
        }
    }

    public static void assertArrayEquals(double[] expected, double[] actual, double delta) {
        if (expected == null || actual == null || expected.length != actual.length) {
            if (expected != actual) {
                failWith("array length/null mismatch");
            }
            return;
        }
        for (int i = 0; i < expected.length; i++) {
            if (Math.abs(expected[i] - actual[i]) > delta) {
                failWith("arrays first differed at element [" + i + "]; expected:<" + expected[i]
                        + "> but was:<" + actual[i] + ">");
            }
        }
    }

    public static void assertArrayEquals(double[] expected, double[] actual, double delta,
            String message) {
        try {
            assertArrayEquals(expected, actual, delta);
        } catch (AssertionError e) {
            failWith(message + " ==> " + e.getMessage());
        }
    }

    public static void assertArrayEquals(Object[] expected, Object[] actual) {
        if (!java.util.Arrays.deepEquals(expected, actual)) {
            failWith("array contents differ");
        }
    }

    public static void assertArrayEquals(Object[] expected, Object[] actual, String message) {
        if (!java.util.Arrays.deepEquals(expected, actual)) {
            failWith(message + " ==> array contents differ");
        }
    }

    public static void assertArrayEquals(String[] expected, String[] actual) {
        assertArrayEquals((Object[]) expected, (Object[]) actual);
    }

    public static <T extends Throwable> T assertThrows(Class<T> expectedType, Executable executable) {
        try {
            executable.execute();
        } catch (Throwable t) {
            if (expectedType.isInstance(t)) {
                return expectedType.cast(t);
            }
            AssertionError error = new AssertionError("unexpected exception type thrown: expected <"
                    + expectedType.getName() + "> but was <" + t.getClass().getName() + ">");
            error.initCause(t);
            throw error;
        }
        failWith("expected " + expectedType.getName() + " to be thrown, but nothing was thrown");
        return null; // unreachable
    }

    public static <T extends Throwable> T assertThrows(Class<T> expectedType, Executable executable,
            String message) {
        try {
            executable.execute();
        } catch (Throwable t) {
            if (expectedType.isInstance(t)) {
                return expectedType.cast(t);
            }
            failWith(message + " ==> unexpected exception type thrown: <" + t.getClass().getName() + ">");
            return null;
        }
        failWith(message + " ==> expected " + expectedType.getName()
                + " to be thrown, but nothing was thrown");
        return null;
    }

    public static void assertDoesNotThrow(Executable executable) {
        try {
            executable.execute();
        } catch (Throwable t) {
            AssertionError error = new AssertionError(
                    "unexpected exception thrown: " + t.getClass().getName() + ": " + t.getMessage());
            error.initCause(t);
            throw error;
        }
    }

    public static void assertDoesNotThrow(Executable executable, String message) {
        try {
            executable.execute();
        } catch (Throwable t) {
            AssertionError error = new AssertionError(message + " ==> unexpected exception thrown: " + t);
            error.initCause(t);
            throw error;
        }
    }

    public static <T> T assertDoesNotThrow(ThrowingSupplier<T> supplier) {
        try {
            return supplier.get();
        } catch (Throwable t) {
            AssertionError error = new AssertionError("unexpected exception thrown: " + t);
            error.initCause(t);
            throw error;
        }
    }

    public static <T> T assertInstanceOf(Class<T> expectedType, Object actual) {
        if (!expectedType.isInstance(actual)) {
            failWith("expected instance of <" + expectedType.getName() + "> but was <"
                    + (actual == null ? "null" : actual.getClass().getName()) + ">");
        }
        return expectedType.cast(actual);
    }
}
