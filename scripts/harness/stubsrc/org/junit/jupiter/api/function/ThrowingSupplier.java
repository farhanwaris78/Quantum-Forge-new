package org.junit.jupiter.api.function;
@FunctionalInterface
public interface ThrowingSupplier<T> { T get() throws Throwable; }
