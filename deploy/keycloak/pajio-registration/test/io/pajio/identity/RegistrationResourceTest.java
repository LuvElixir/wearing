package io.pajio.identity;

import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import java.io.ByteArrayInputStream;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import org.keycloak.models.KeycloakContext;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakTransactionManager;
import org.keycloak.models.RealmModel;
import org.keycloak.models.SubjectCredentialManager;
import org.keycloak.models.UserModel;
import org.keycloak.models.UserProvider;
import org.keycloak.policy.PasswordPolicyManagerProvider;
import org.keycloak.policy.PolicyError;
import org.keycloak.util.JsonSerialization;

/** No Keycloak database/server/network: real SDK types and JSON/Response implementations. */
public final class RegistrationResourceTest {
    private RegistrationResourceTest() {}
    private static final String AUTH = "Bearer " + "A".repeat(64);
    private static final String INTENT = "pajio_registration_id";
    private static final String FINGERPRINT = "pajio_registration_fingerprint";
    private static int passed;

    private static <T> T stub(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }
    private static Object unexpected(String name) { throw new AssertionError("Unexpected SDK call: " + name); }
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    private static Map<String,Object> data(boolean password) {
        Map<String,Object> data = new HashMap<>(Map.of("username", "fixture.user", "registration_id", "a".repeat(32), "fingerprint", "b".repeat(64)));
        if (password) data.put("password", "Synthet1c-Password");
        return data;
    }
    private static ByteArrayInputStream body(Map<String,Object> data) throws Exception {
        return new ByteArrayInputStream(JsonSerialization.writeValueAsBytes(data));
    }
    private static void response(Response response, int expected, String code) {
        try (response) {
            check(response.getStatus() == expected, "Wrong response status");
            check("no-store".equals(response.getHeaderString("Cache-Control")), "Response can be cached");
            if (code != null) check(code.equals(((Map<?,?>)response.getEntity()).get("code")), "Wrong response code");
            else check(((Map<?,?>)response.getEntity()).keySet().equals(java.util.Set.of("subject", "registration_id")), "Identity leaked fields");
        }
    }

    private static final class Fixture implements AutoCloseable {
        final Path directory = Files.createTempDirectory("pajio-registration-test-");
        final Path keyFile = directory.resolve("key");
        final Map<String,String> attributes = new HashMap<>();
        boolean enabled;
        boolean present;
        boolean rollback;
        boolean denyPolicy;
        boolean failCredential;
        String realmName = "pajio";
        String serviceLink;
        int lookups;
        int additions;
        int credentialWrites;
        int attributeWrites;
        final UserModel user;
        final RegistrationResource resource;
        Fixture() throws Exception {
            Files.writeString(keyFile, "A".repeat(64));
            SubjectCredentialManager credentials = stub(SubjectCredentialManager.class, (p,m,a) -> {
                if (m.getName().equals("updateCredential")) { credentialWrites++; return !failCredential; }
                return unexpected(m.getName());
            });
            user = stub(UserModel.class, (p,m,a) -> switch (m.getName()) {
                case "isEnabled" -> enabled;
                case "getServiceAccountClientLink" -> serviceLink;
                case "getFirstAttribute" -> attributes.get((String)a[0]);
                case "getId" -> "synthetic-subject";
                case "setEnabled" -> { enabled = (Boolean)a[0]; yield null; }
                case "setSingleAttribute" -> { attributeWrites++; attributes.put((String)a[0], (String)a[1]); yield null; }
                case "credentialManager" -> credentials;
                default -> unexpected(m.getName());
            });
            RealmModel realm = stub(RealmModel.class, (p,m,a) -> m.getName().equals("getName") ? realmName : unexpected(m.getName()));
            KeycloakContext context = stub(KeycloakContext.class, (p,m,a) -> m.getName().equals("getRealm") ? realm : unexpected(m.getName()));
            UserProvider users = stub(UserProvider.class, (p,m,a) -> switch (m.getName()) {
                case "getUserByUsername" -> { lookups++; yield present ? user : null; }
                case "addUser" -> { check(!present, "Duplicate creation"); additions++; present = true; yield user; }
                default -> unexpected(m.getName());
            });
            PasswordPolicyManagerProvider policies = stub(PasswordPolicyManagerProvider.class, (p,m,a) -> m.getName().equals("validate") ? (denyPolicy ? new PolicyError("synthetic") : null) : unexpected(m.getName()));
            KeycloakTransactionManager transactions = stub(KeycloakTransactionManager.class, (p,m,a) -> {
                if (m.getName().equals("setRollbackOnly")) { rollback = true; return null; }
                return unexpected(m.getName());
            });
            KeycloakSession session = stub(KeycloakSession.class, (p,m,a) -> switch(m.getName()) {
                case "getContext" -> context;
                case "users" -> users;
                case "getTransactionManager" -> transactions;
                case "getProvider" -> { check(a[0] == PasswordPolicyManagerProvider.class, "Unexpected provider"); yield policies; }
                default -> unexpected(m.getName());
            });
            resource = new RegistrationResource(session, keyFile);
        }
        void existing() { present = true; enabled = true; attributes.put(INTENT,"a".repeat(32)); attributes.put(FINGERPRINT,"b".repeat(64)); }
        public void close() throws java.io.IOException { Files.deleteIfExists(keyFile); Files.delete(directory); }
    }
    private interface Case { void run(Fixture fixture) throws Exception; }
    private static void test(String name, Case body) throws Exception {
        try (Fixture fixture = new Fixture()) { body.run(fixture); passed++; System.out.println("PASS " + name); }
    }
    public static void main(String[] args) throws Exception {
        check(RegistrationResource.class.isAnnotationPresent(Provider.class), "Missing REST discovery annotation");
        test("denied authorization has no storage access", f -> {
            response(f.resource.create("Bearer wrong", body(data(true))),403,"registration_denied");
            response(f.resource.inspect(null, body(data(false))),403,"registration_denied");
            check(f.lookups == 0 && f.additions == 0, "Denied request accessed users");
        });
        test("realm and key checks fail closed", f -> {
            f.realmName = "master";
            response(f.resource.create(AUTH, body(data(true))),403,"registration_denied");
            f.realmName = "pajio";
            Files.writeString(f.keyFile, "short");
            response(f.resource.create(AUTH, body(data(true))),403,"registration_denied");
            Files.delete(f.keyFile);
            Files.createSymbolicLink(f.keyFile, Path.of("missing"));
            response(f.resource.create(AUTH, body(data(true))),403,"registration_denied");
            check(f.lookups == 0, "Invalid realm/key accessed users");
        });
        test("strict body and length bounds reject before storage", f -> {
            for (String malformed : new String[]{"null", "[]", "{", " ".repeat(4097)}) {
                response(f.resource.create(AUTH, new ByteArrayInputStream(malformed.getBytes(StandardCharsets.UTF_8))),422,"registration_invalid");
            }
            Map<String,Object> extra = data(true); extra.put("roles", "admin");
            response(f.resource.create(AUTH, body(extra)),422,"registration_invalid");
            for (String password : new String[]{"short", "x".repeat(129), "bad\npassword-123"}) {
                var invalid = data(true); invalid.put("password",password);
                response(f.resource.create(AUTH, body(invalid)),422,"registration_invalid");
            }
            check(f.lookups == 0, "Invalid request accessed users");
        });
        test("new user create and idempotent retry", f -> {
            response(f.resource.create(AUTH, body(data(true))),200,null);
            check(f.enabled && f.additions == 1 && f.credentialWrites == 1 && f.attributeWrites == 2, "Creation incomplete");
            var retry = data(true); retry.put("password","Different-Password99");
            response(f.resource.create(AUTH,body(retry)),200,null);
            check(f.additions == 1 && f.credentialWrites == 1 && f.attributeWrites == 2, "Retry changed existing user");
        });
        test("password length counts unicode code points", f -> {
            var tooShort = data(true); tooShort.put("password", "🌙".repeat(11));
            response(f.resource.create(AUTH,body(tooShort)),422,"registration_invalid");
            var maximum = data(true); maximum.put("password", "🌙".repeat(128));
            response(f.resource.create(AUTH,body(maximum)),200,null);
            check(f.additions == 1 && f.credentialWrites == 1, "Unicode length contract rejected valid maximum");
        });
        test("conflicting intent never resets credentials", f -> {
            f.existing(); var conflict = data(true); conflict.put("registration_id", "c".repeat(32));
            response(f.resource.create(AUTH,body(conflict)),409,"username_unavailable");
            check(f.credentialWrites == 0 && f.attributeWrites == 0 && f.additions == 0, "Conflict mutated user");
        });
        test("service account and disabled user cannot match", f -> {
            f.existing(); f.serviceLink = "synthetic-client";
            response(f.resource.create(AUTH,body(data(true))),409,"username_unavailable");
            f.serviceLink = null; f.enabled = false;
            response(f.resource.inspect(AUTH,body(data(false))),409,"username_unavailable");
            check(f.credentialWrites == 0 && f.attributeWrites == 0, "Protected user mutated");
        });
        test("password policy rejects before create", f -> {
            f.denyPolicy = true;
            response(f.resource.create(AUTH,body(data(true))),422,"password_policy");
            check(f.additions == 0 && f.credentialWrites == 0, "Policy failure created user");
        });
        test("credential failure marks transaction rollback", f -> {
            f.failCredential = true;
            response(f.resource.create(AUTH,body(data(true))),503,"registration_unknown");
            check(f.rollback, "Partial creation not rolled back");
        });
        test("inspect is read only and requires matching intent", f -> {
            response(f.resource.inspect(AUTH,body(data(false))),404,"registration_absent");
            f.existing(); response(f.resource.inspect(AUTH,body(data(false))),200,null);
            var mismatch = data(false); mismatch.put("fingerprint","d".repeat(64));
            response(f.resource.inspect(AUTH,body(mismatch)),409,"username_unavailable");
            check(f.additions == 0 && f.credentialWrites == 0 && f.attributeWrites == 0, "Inspect mutated user");
        });
        System.out.println("RegistrationResource tests passed: " + passed);
    }
}
