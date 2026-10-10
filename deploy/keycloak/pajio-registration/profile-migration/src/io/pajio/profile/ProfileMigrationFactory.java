package io.pajio.profile;

import java.nio.file.Path;
import org.keycloak.Config;
import org.keycloak.events.Event;
import org.keycloak.events.EventListenerProvider;
import org.keycloak.events.EventListenerProviderFactory;
import org.keycloak.events.admin.AdminEvent;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.models.utils.PostMigrationEvent;

/** Separate startup extension: no REST resource and no administrative login bypass. */
public final class ProfileMigrationFactory implements EventListenerProviderFactory {
    private static final System.Logger LOG = System.getLogger(ProfileMigrationFactory.class.getName());
    public String getId() { return "pajio-profile-migration-v1"; }
    public void init(Config.Scope config) {}
    public void close() {}
    public EventListenerProvider create(KeycloakSession session) {
        return new EventListenerProvider() {
            public void onEvent(Event event) {}
            public void onEvent(AdminEvent event, boolean includeRepresentation) {}
            public void close() {}
        };
    }
    public void postInit(KeycloakSessionFactory factory) {
        String mode = System.getenv("PAJIO_PROFILE_MIGRATION");
        if (mode == null || mode.isBlank()) return;
        if (!mode.equals("plan-v1") && !mode.equals("apply-v1"))
            throw new IllegalStateException("pajio_profile_migration_invalid_mode");
        factory.register(event -> {
            if (!(event instanceof PostMigrationEvent)) return;
            try {
                String receiptHash = ProfileMigration.run(factory, mode,
                    Path.of("/etc/pajio/profile-migration-v1.json"),
                    Path.of("/var/lib/pajio/profile-migration"));
                LOG.log(System.Logger.Level.INFO, "pajio-profile-migration success receipt_sha256=" + receiptHash);
            } catch (Exception failure) {
                LOG.log(System.Logger.Level.ERROR, "pajio-profile-migration failed error_sha256=" +
                    ProfileMigration.sha((failure.getClass().getName() + ":" + failure.getMessage()).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                // Do not attach the original exception: SDK validation messages can contain profile values.
                throw new IllegalStateException("pajio_profile_migration_failed");
            }
        });
    }
}
