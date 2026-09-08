package org.slf4j.impl;

import java.lang.reflect.Proxy;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.ILoggerFactory;
import org.slf4j.Logger;
import org.slf4j.spi.LoggerFactoryBinder;

/** Converts renderer warnings into failure, without retaining invoice text in logs. */
public final class StaticLoggerBinder implements LoggerFactoryBinder {
    public static String REQUESTED_API_VERSION = "1.7.36";
    private static final StaticLoggerBinder INSTANCE = new StaticLoggerBinder();
    private static final AtomicBoolean INCOMPLETE = new AtomicBoolean();
    private final ILoggerFactory factory = name -> (Logger) Proxy.newProxyInstance(
        Logger.class.getClassLoader(), new Class<?>[]{Logger.class}, (proxy, method, args) -> {
            String operation = method.getName();
            if (operation.equals("hashCode")) return System.identityHashCode(proxy);
            if (operation.equals("equals")) return proxy == args[0];
            if (operation.equals("toString")) return name;
            if (operation.equals("getName")) return name;
            if (operation.startsWith("is")) return operation.equals("isWarnEnabled") || operation.equals("isErrorEnabled");
            // OFDRW catches PageBlock/font/stamp exceptions and otherwise returns
            // a partially drawn page. Such a PNG must not be advertised as success.
            if ((operation.equals("warn") && name.startsWith("org.ofdrw.converter")) || operation.equals("error")) {
                INCOMPLETE.set(true);
            }
            return null;
        });
    public static StaticLoggerBinder getSingleton() { return INSTANCE; }
    public static boolean incomplete() { return INCOMPLETE.get(); }
    public ILoggerFactory getLoggerFactory() { return factory; }
    public String getLoggerFactoryClassStr() { return factory.getClass().getName(); }
}
