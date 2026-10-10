package io.pajio.theme;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.provider.ProviderEvent;
import org.keycloak.provider.ProviderEventListener;

/** Tests startup listener registration only; never publishes a PostMigrationEvent. */
public final class ThemeMigrationFactoryTest {
    private ThemeMigrationFactoryTest() {}
    public static void main(String[] args) {
        var listeners = new ArrayList<ProviderEventListener>();
        var factory = (KeycloakSessionFactory)Proxy.newProxyInstance(KeycloakSessionFactory.class.getClassLoader(), new Class<?>[]{KeycloakSessionFactory.class}, (p,m,a) -> {
            if (m.getName().equals("register")) { listeners.add((ProviderEventListener)a[0]); return null; }
            throw new AssertionError("Unexpected SDK access during registration: " + m.getName());
        });
        var provider = new ThemeMigrationFactory();
        String mode = System.getenv("PAJIO_THEME_MIGRATION");
        boolean valid = "plan-v1".equals(mode) || "apply-v1".equals(mode);
        boolean absent = mode == null || mode.isBlank();
        try {
            provider.postInit(factory);
            if (!valid && !absent) throw new AssertionError("Invalid mode accepted");
        } catch (IllegalStateException expected) {
            if (valid || absent) throw new AssertionError("Valid mode rejected");
        }
        if (listeners.size() != (valid ? 1 : 0)) throw new AssertionError("Wrong listener count");
        // Other provider lifecycle events must not inspect files or touch the realm.
        listeners.forEach(listener -> listener.onEvent(new ProviderEvent() {}));
        System.out.println("PASS migration startup mode gate " + (absent ? "unset" : valid ? mode : "invalid"));
    }
}
