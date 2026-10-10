package io.pajio.cleanup;

import java.nio.file.Path;
import org.keycloak.Config;
import org.keycloak.events.Event;
import org.keycloak.events.EventListenerProvider;
import org.keycloak.events.EventListenerProviderFactory;
import org.keycloak.events.admin.AdminEvent;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.models.utils.PostMigrationEvent;

/** One-time startup maintenance. No REST endpoint or authentication bypass. */
public final class QACleanupFactory implements EventListenerProviderFactory {
    private static final System.Logger LOG = System.getLogger(QACleanupFactory.class.getName());
    public String getId() { return "pajio-qa-cleanup-v1"; }
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
        String mode = System.getenv("PAJIO_QA_CLEANUP");
        if (mode == null || mode.isBlank()) return;
        if (!mode.equals("plan-v1") && !mode.equals("apply-v1"))
            throw new IllegalStateException("pajio_qa_cleanup_invalid_mode");
        factory.register(event -> {
            if (!(event instanceof PostMigrationEvent)) return;
            try {
                String receiptHash = QACleanup.run(factory, mode,
                    Path.of("/etc/pajio/qa-cleanup-v1.json"), Path.of("/var/lib/pajio/qa-cleanup-v1"));
                LOG.log(System.Logger.Level.INFO, "pajio-qa-cleanup success receipt_sha256=" + receiptHash);
            } catch (Exception failure) {
                LOG.log(System.Logger.Level.ERROR, "pajio-qa-cleanup failed error_sha256=" +
                    QACleanup.sha((failure.getClass().getName() + ":" + failure.getMessage()).getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                throw new IllegalStateException("pajio_qa_cleanup_failed");
            }
        });
    }
}
