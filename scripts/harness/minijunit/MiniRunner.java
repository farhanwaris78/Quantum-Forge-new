package minijunit;

import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Executable;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.Parameter;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.DisabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.junit.jupiter.api.io.TempDir;

/**
 * Tiny reflective test runner for the mini JUnit 5 surface. Usage:
 * {@code java minijunit.MiniRunner runlist.txt} where the runlist holds one
 * fully qualified test class name per line (# comments allowed). Exit code 0
 * when every executed test passes.
 */
public final class MiniRunner {

    private static final List<Path> TEMP_DIRS = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("usage: MiniRunner <runlist-file>");
            System.exit(2);
        }
        List<String> classNames = new ArrayList<>();
        for (String line : Files.readAllLines(Path.of(args[0]))) {
            String trimmed = line.trim();
            if (!trimmed.isEmpty() && !trimmed.startsWith("#")) {
                classNames.add(trimmed);
            }
        }
        int totalTests = 0;
        int failedTests = 0;
        int skippedTests = 0;
        List<String> failures = new ArrayList<>();
        int failedClasses = 0;
        for (String className : classNames) {
            Class<?> testClass;
            try {
                testClass = Class.forName(className);
            } catch (Throwable t) {
                System.out.println("CLASS-LOAD-FAIL " + className + " : " + t);
                failures.add(className + " <class load> : " + t);
                failedClasses++;
                continue;
            }
            Runner runner = new Runner(testClass);
            Result result = runner.run();
            totalTests += result.executed;
            failedTests += result.failed.size();
            skippedTests += result.skipped;
            if (!result.failed.isEmpty()) {
                failedClasses++;
            }
            for (String failure : result.failed) {
                failures.add(className + " " + failure);
            }
            System.out.printf("%-72s executed=%d failed=%d skipped=%d%n",
                    className, result.executed, result.failed.size(), result.skipped);
        }
        System.out.println("============================================================");
        System.out.printf("TOTAL classes=%d failedClasses=%d tests=%d failed=%d skipped=%d%n",
                classNames.size(), failedClasses, totalTests, failedTests, skippedTests);
        if (!failures.isEmpty()) {
            System.out.println("FAILURES:");
            for (String failure : failures) {
                System.out.println("  - " + failure);
            }
            System.exit(1);
        }
        System.exit(0);
    }

    private static final class Result {
        int executed;
        int skipped;
        final List<String> failed = new ArrayList<>();
    }

    private static final class Runner {
        private final Class<?> testClass;

        Runner(Class<?> testClass) {
            this.testClass = testClass;
        }

        Result run() {
            Result result = new Result();
            if (isDisabled(testClass)) {
                int count = testMethods().size();
                result.skipped += count;
                return result;
            }
            try {
                for (Method beforeAll : annotated(BeforeAll.class, true)) {
                    beforeAll.setAccessible(true);
                    beforeAll.invoke(null);
                }
            } catch (InvocationTargetException | IllegalAccessException e) {
                result.failed.add("<@BeforeAll> : " + unwrap(e));
                return result;
            }
            for (Method testMethod : testMethods()) {
                if (isDisabled(testMethod) || testMethod.isSynthetic()) {
                    result.skipped++;
                    continue;
                }
                result.executed++;
                runSingle(testMethod, result);
            }
            try {
                for (Method afterAll : annotated(AfterAll.class, true)) {
                    afterAll.setAccessible(true);
                    afterAll.invoke(null);
                }
            } catch (InvocationTargetException | IllegalAccessException e) {
                result.failed.add("<@AfterAll> : " + unwrap(e));
            }
            return result;
        }

        private void runSingle(Method testMethod, Result result) {
            Object instance;
            try {
                Constructor<?> ctor = testClass.getDeclaredConstructor();
                ctor.setAccessible(true);
                instance = ctor.newInstance();
            } catch (ReflectiveOperationException e) {
                result.failed.add(testMethod.getName() + " <instantiate> : " + unwrap(e));
                return;
            }
            try {
                injectTempDirFields(instance);
                for (Method beforeEach : annotated(BeforeEach.class, false)) {
                    beforeEach.setAccessible(true);
                    beforeEach.invoke(instance);
                }
                Object[] params = resolveParams(testMethod);
                testMethod.setAccessible(true);
                testMethod.invoke(instance, params);
            } catch (InvocationTargetException e) {
                Throwable cause = e.getCause() == null ? e : e.getCause();
                result.failed.add(testMethod.getName() + " : " + describe(cause));
            } catch (Throwable e) {
                result.failed.add(testMethod.getName() + " : " + describe(e));
            } finally {
                try {
                    for (Method afterEach : annotated(AfterEach.class, false)) {
                        afterEach.setAccessible(true);
                        afterEach.invoke(instance);
                    }
                } catch (Throwable t) {
                    result.failed.add(testMethod.getName() + " <@AfterEach> : " + describe(t));
                }
                cleanupTempDirs();
            }
        }

        private List<Method> testMethods() {
            List<Method> out = new ArrayList<>();
            for (Class<?> c = testClass; c != null && c != Object.class; c = c.getSuperclass()) {
                for (Method m : c.getDeclaredMethods()) {
                    if (m.isAnnotationPresent(Test.class)) {
                        out.add(m);
                    }
                }
            }
            out.sort(Comparator.comparing(Method::getName));
            return out;
        }

        private List<Method> annotated(Class<? extends java.lang.annotation.Annotation> ann,
                boolean statik) {
            List<Method> out = new ArrayList<>();
            List<Class<?>> hierarchy = new ArrayList<>();
            for (Class<?> c = testClass; c != null && c != Object.class; c = c.getSuperclass()) {
                hierarchy.add(0, c);
            }
            for (Class<?> c : hierarchy) {
                for (Method m : c.getDeclaredMethods()) {
                    if (m.isAnnotationPresent(ann) && Modifier.isStatic(m.getModifiers()) == statik) {
                        out.add(m);
                    }
                }
            }
            return out;
        }

        private static boolean isDisabled(java.lang.reflect.AnnotatedElement element) {
            if (element.isAnnotationPresent(Disabled.class)) {
                return true;
            }
            DisabledOnOs disabledOnOs = element.getAnnotation(DisabledOnOs.class);
            if (disabledOnOs != null) {
                return Arrays.stream(disabledOnOs.value()).anyMatch(OS::isCurrentOs);
            }
            return false;
        }

        private void injectTempDirFields(Object instance) throws IOException, IllegalAccessException {
            for (Class<?> c = testClass; c != null && c != Object.class; c = c.getSuperclass()) {
                for (Field field : c.getDeclaredFields()) {
                    if (!field.isAnnotationPresent(TempDir.class) || Modifier.isStatic(field.getModifiers())) {
                        continue;
                    }
                    Path dir = Files.createTempDirectory("minijunit");
                    TEMP_DIRS.add(dir);
                    field.setAccessible(true);
                    if (field.getType() == Path.class) {
                        field.set(instance, dir);
                    } else if (field.getType() == java.io.File.class) {
                        field.set(instance, dir.toFile());
                    } else if (field.getType() == String.class) {
                        field.set(instance, dir.toString());
                    } else {
                        throw new IllegalStateException("unsupported @TempDir field type: " + field.getType());
                    }
                }
            }
        }

        private static Object[] resolveParams(Executable executable) throws IOException {
            Parameter[] parameters = executable.getParameters();
            Object[] out = new Object[parameters.length];
            for (int i = 0; i < parameters.length; i++) {
                Parameter parameter = parameters[i];
                if (parameter.isAnnotationPresent(TempDir.class)) {
                    Path dir = Files.createTempDirectory("minijunit");
                    TEMP_DIRS.add(dir);
                    if (parameter.getType() == Path.class) {
                        out[i] = dir;
                    } else if (parameter.getType() == java.io.File.class) {
                        out[i] = dir.toFile();
                    } else {
                        out[i] = dir.toString();
                    }
                } else {
                    throw new IllegalStateException("unsupported parameter: " + parameter);
                }
            }
            return out;
        }

        private static void cleanupTempDirs() {
            for (Path dir : TEMP_DIRS) {
                try {
                    if (!Files.exists(dir)) {
                        continue;
                    }
                    Files.walk(dir).sorted(Comparator.reverseOrder()).forEach(p -> {
                        try {
                            Files.deleteIfExists(p);
                        } catch (IOException ignored) {
                            // best effort cleanup
                        }
                    });
                } catch (IOException ignored) {
                    // best effort cleanup
                }
            }
            TEMP_DIRS.clear();
        }

        private static String unwrap(Exception e) {
            if (e instanceof InvocationTargetException ite && ite.getCause() != null) {
                return describe(ite.getCause());
            }
            return describe(e);
        }

        private static String describe(Throwable t) {
            StringBuilder sb = new StringBuilder();
            sb.append(t.getClass().getName());
            if (t.getMessage() != null) {
                sb.append(": ").append(t.getMessage());
            }
            StackTraceElement[] trace = t.getStackTrace();
            int shown = 0;
            for (StackTraceElement el : trace) {
                if (el.getClassName().startsWith("minijunit.")
                        || el.getClassName().startsWith("org.junit.jupiter.api.Assert")) {
                    continue;
                }
                sb.append("\n      at ").append(el);
                if (++shown >= 5) {
                    break;
                }
            }
            return sb.toString();
        }
    }
}
