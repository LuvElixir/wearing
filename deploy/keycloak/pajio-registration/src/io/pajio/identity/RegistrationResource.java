package io.pajio.identity;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.HeaderParam;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.Map;
import java.util.Set;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.UserCredentialModel;
import org.keycloak.models.UserModel;
import org.keycloak.policy.PasswordPolicyManagerProvider;
import org.keycloak.util.JsonSerialization;

@Produces("application/json")
@Consumes("application/json")
@Provider
public final class RegistrationResource {
    private final KeycloakSession session;
    private final java.nio.file.Path keyFile;
    private static final String INTENT = "pajio_registration_id";
    private static final String FINGERPRINT = "pajio_registration_fingerprint";
    public RegistrationResource(KeycloakSession session) {
        this(session, java.nio.file.Path.of("/etc/pajio/registration-provider.key"));
    }
    // Package-private only for isolated tests; the REST factory always uses the fixed path.
    RegistrationResource(KeycloakSession session, java.nio.file.Path keyFile) {
        this.session = session;
        this.keyFile = keyFile;
    }

    private boolean authorized(String authorization) {
        try {
            if (!"pajio".equals(session.getContext().getRealm().getName())) return false;
            var file = keyFile;
            if (Files.isSymbolicLink(file) || !Files.isRegularFile(file) || Files.size(file) > 256) return false;
            String key = Files.readString(file).strip();
            return key.matches("[A-Za-z0-9_-]{64}") && authorization != null
                && MessageDigest.isEqual(("Bearer " + key).getBytes(StandardCharsets.US_ASCII),
                                          authorization.getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignored) { return false; }
    }
    private Response result(int status, String code) {
        return Response.status(status).header("Cache-Control", "no-store")
            .entity(Map.of("code", code)).build();
    }
    private Response identity(UserModel user) {
        return Response.ok(Map.of("subject", user.getId(), "registration_id", user.getFirstAttribute(INTENT)))
            .header("Cache-Control", "no-store").build();
    }
    @SuppressWarnings("unchecked")
    private Map<String,Object> body(InputStream input, boolean create) throws Exception {
        byte[] bytes = input.readNBytes(4097);
        if (bytes.length > 4096) throw new IllegalArgumentException();
        Map<String,Object> value = JsonSerialization.readValue(bytes, Map.class);
        var fields = create ? Set.of("username", "password", "registration_id", "fingerprint")
                            : Set.of("username", "registration_id", "fingerprint");
        if (!value.keySet().equals(fields) || !value.values().stream().allMatch(v -> v instanceof String))
            throw new IllegalArgumentException();
        if (!((String)value.get("username")).matches("[a-z][a-z0-9_.-]{3,31}")
            || !((String)value.get("registration_id")).matches("[a-f0-9]{32}")
            || !((String)value.get("fingerprint")).matches("[a-f0-9]{64}")) throw new IllegalArgumentException();
        if (create) {
            String password = (String)value.get("password");
            int passwordLength = password.codePointCount(0, password.length());
            if (passwordLength < 12 || passwordLength > 128
                || password.codePoints().anyMatch(c -> Character.isISOControl(c))) throw new IllegalArgumentException();
        }
        return value;
    }
    private boolean matches(UserModel user, Map<String,Object> data) {
        return user.isEnabled() && user.getServiceAccountClientLink() == null
            && data.get("registration_id").equals(user.getFirstAttribute(INTENT))
            && data.get("fingerprint").equals(user.getFirstAttribute(FINGERPRINT));
    }
    @POST @Path("inspect")
    public Response inspect(@HeaderParam("Authorization") String auth, InputStream input) {
        if (!authorized(auth)) return result(403, "registration_denied");
        try {
            var data = body(input, false);
            var user = session.users().getUserByUsername(session.getContext().getRealm(), (String)data.get("username"));
            if (user == null) return result(404, "registration_absent");
            return matches(user,data) ? identity(user) : result(409, "username_unavailable");
        } catch (Exception ignored) { return result(422, "registration_invalid"); }
    }
    @POST @Path("create")
    public Response create(@HeaderParam("Authorization") String auth, InputStream input) {
        if (!authorized(auth)) return result(403, "registration_denied");
        Map<String,Object> data;
        try { data = body(input, true); }
        catch (Exception ignored) { return result(422, "registration_invalid"); }
        var realm = session.getContext().getRealm();
        String username = (String)data.get("username"), password = (String)data.get("password");
        var old = session.users().getUserByUsername(realm, username);
        if (old != null) return matches(old,data) ? identity(old) : result(409, "username_unavailable");
        try {
            if (session.getProvider(PasswordPolicyManagerProvider.class).validate(username, password) != null)
                return result(422, "password_policy");
            var user = session.users().addUser(realm, username);
            user.setEnabled(true);
            user.setSingleAttribute(INTENT, (String)data.get("registration_id"));
            user.setSingleAttribute(FINGERPRINT, (String)data.get("fingerprint"));
            if (!user.credentialManager().updateCredential(UserCredentialModel.password(password)))
                throw new IllegalStateException();
            return identity(user);
        } catch (Exception ignored) {
            session.getTransactionManager().setRollbackOnly();
            return result(503, "registration_unknown");
        }
    }
}
