package io.pajio.identity;

import org.keycloak.Config;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.services.resource.RealmResourceProvider;
import org.keycloak.services.resource.RealmResourceProviderFactory;

/** A create-only adapter, not an administrative API or public registration flow. */
public final class RegistrationFactory implements RealmResourceProviderFactory {
    public RealmResourceProvider create(KeycloakSession session) {
        return new RealmResourceProvider() {
            public Object getResource() { return new RegistrationResource(session); }
            public void close() {}
        };
    }
    public String getId() { return "pajio-registration"; }
    public void init(Config.Scope config) {}
    public void postInit(KeycloakSessionFactory factory) {}
    public void close() {}
}
