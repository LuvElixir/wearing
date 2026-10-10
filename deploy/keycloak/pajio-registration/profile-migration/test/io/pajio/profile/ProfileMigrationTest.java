package io.pajio.profile;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.HashMap;
import java.util.Map;
import org.keycloak.models.KeycloakContext;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.RealmProvider;
import org.keycloak.models.RequiredActionProviderModel;
import org.keycloak.representations.userprofile.config.UPAttribute;
import org.keycloak.representations.userprofile.config.UPConfig;
import org.keycloak.userprofile.UserProfileProvider;
import org.keycloak.util.JsonSerialization;

public final class ProfileMigrationTest {
    private ProfileMigrationTest() {}
    private static int passed;
    private static void check(boolean valid, String message) { if (!valid) throw new AssertionError(message); }
    private static Object unexpected(String name) { throw new AssertionError("Unexpected SDK call: " + name); }
    private static <T> T stub(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }
    private interface Action { void run() throws Exception; }
    private static void reject(Action action) throws Exception {
        try { action.run(); } catch (IllegalStateException expected) { return; }
        throw new AssertionError("Expected fail-closed rejection");
    }
    private static UPConfig upstream() throws IOException {
        try (var source = ProfileMigrationTest.class.getClassLoader().getResourceAsStream("org/keycloak/userprofile/config/keycloak-default-user-profile.json")) {
            check(source != null, "Actual Keycloak default profile resource missing");
            return JsonSerialization.readValue(source, UPConfig.class);
        }
    }
    private static final class Fixture implements AutoCloseable {
        final Path directory = Files.createTempDirectory("pajio-profile-sdk-test-", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        final Map<String,String> markers = new HashMap<>();
        final RequiredActionProviderModel verify = new RequiredActionProviderModel();
        UPConfig current = upstream();
        String realmName = "pajio";
        boolean registration;
        boolean emailUsername;
        boolean verifyEmail;
        boolean failSet;
        int profileWrites;
        int markerWrites;
        final KeycloakSession session;
        Fixture() throws IOException {
            verify.setEnabled(true);
            RealmModel realm = stub(RealmModel.class, (p,m,a) -> switch(m.getName()) {
                case "getName" -> realmName;
                case "getId" -> "synthetic-realm-id";
                case "isRegistrationAllowed" -> registration;
                case "isRegistrationEmailAsUsername" -> emailUsername;
                case "isVerifyEmail" -> verifyEmail;
                case "getRequiredActionProviderByAlias" -> { check("VERIFY_PROFILE".equals(a[0]), "Unexpected action"); yield verify; }
                case "getAttribute" -> markers.get((String)a[0]);
                case "setAttribute" -> { check(ProfileMigration.MARKER.equals(a[0]), "Unexpected realm mutation"); markerWrites++; markers.put((String)a[0], (String)a[1]); yield null; }
                default -> unexpected(m.getName());
            });
            RealmProvider realms = stub(RealmProvider.class, (p,m,a) -> {
                check(m.getName().equals("getRealmByName") && "pajio".equals(a[0]), "Wrong realm lookup"); return realm;
            });
            KeycloakContext context = stub(KeycloakContext.class, (p,m,a) -> {
                check(m.getName().equals("setRealm") && a[0] == realm, "Wrong realm context"); return null;
            });
            UserProfileProvider provider = stub(UserProfileProvider.class, (p,m,a) -> switch (m.getName()) {
                case "getConfiguration" -> current;
                case "setConfiguration" -> { if (failSet) throw new IllegalStateException("synthetic_failure"); profileWrites++; current = (UPConfig)a[0]; yield null; }
                default -> unexpected(m.getName());
            });
            session = stub(KeycloakSession.class, (p,m,a) -> switch(m.getName()) {
                case "realms" -> realms;
                case "getContext" -> context;
                case "getProvider" -> { check(a[0] == UserProfileProvider.class, "Unexpected provider"); yield provider; }
                default -> unexpected(m.getName());
            });
        }
        JsonNode plan() { return ProfileMigration.process(session, "plan-v1", ProfileMigration.JSON.createObjectNode(), directory, false); }
        JsonNode flag() throws IOException {
            var plan = ProfileMigration.read(directory.resolve("plan-v1.json"), 1024 * 1024);
            var flag = ProfileMigration.JSON.createObjectNode().put("mode", "apply-v1").put("realm", "pajio");
            for (String field : java.util.Set.of("realm_id", "pre_sha256", "post_sha256")) flag.set(field, plan.get(field));
            return flag;
        }
        JsonNode apply(boolean verifyOnly) throws IOException { return ProfileMigration.process(session, "apply-v1", flag(), directory, verifyOnly); }
        public void close() throws IOException {
            try (var paths = Files.list(directory)) { for (Path path : paths.toList()) Files.delete(path); }
            Files.delete(directory);
        }
    }
    private interface Case { void run(Fixture fixture) throws Exception; }
    private static void test(String name, Case action) throws Exception {
        try (Fixture fixture = new Fixture()) { action.run(fixture); passed++; System.out.println("PASS " + name); }
    }
    public static void main(String[] args) throws Exception {
        test("review transform preserves unrelated actual SDK profile", f -> {
            f.current.getAttributes().add(new UPAttribute("custom", Map.of("synthetic", "retained")));
            byte[] original = ProfileMigration.bytes(f.current);
            UPConfig candidate = ProfileMigration.transform(f.current);
            check(java.util.Arrays.equals(original, ProfileMigration.bytes(f.current)), "Transform mutated original");
            check(candidate.getAttribute("username").equals(f.current.getAttribute("username")), "Username changed");
            check(candidate.getAttribute("custom").equals(f.current.getAttribute("custom")), "Custom changed");
            for (String name : java.util.Set.of("email", "firstName", "lastName")) {
                check(candidate.getAttribute(name).getRequired() == null, "Required field retained");
                check(candidate.getAttribute(name).getValidations().equals(f.current.getAttribute(name).getValidations()), "Validator changed");
            }
            var node = ProfileMigration.JSON.readTree(ProfileMigration.bytes(candidate));
            for (JsonNode attr : node.path("attributes")) if (attr.path("name").asText().startsWith("pajio_registration_")) {
                check(attr.path("permissions").path("edit").toString().equals("[\"admin\"]"), "Marker user editable");
                check(attr.path("permissions").path("view").toString().equals("[\"admin\"]"), "Marker user visible");
            }
        });
        test("plan is read only immutable and private", f -> {
            ProfileMigration.privateDirectory(f.directory);
            JsonNode first = f.plan(); check(first.equals(f.plan()), "Plan not deterministic");
            check(f.profileWrites == 0 && f.markerWrites == 0, "Plan mutated realm");
            check(Files.getPosixFilePermissions(f.directory.resolve("plan-v1.json")).equals(PosixFilePermissions.fromString("rw-------")), "Backup permissions");
        });
        test("apply then startup verification never rewrites", f -> {
            f.plan(); JsonNode receipt = f.apply(false); check(receipt.equals(f.apply(true)), "Verification mismatch");
            check(receipt.equals(f.apply(false)), "Repeat mismatch");
            check(f.profileWrites == 1 && f.markerWrites == 1, "Completed migration rewrote config");
            check(!f.registration && !f.emailUsername && !f.verifyEmail && f.verify.isEnabled(), "Authentication flags changed");
        });
        test("post-completion admin changes are never overwritten", f -> {
            f.plan(); f.apply(false); f.current.getAttribute("username").setDisplayName("later-change");
            reject(() -> f.apply(false)); check(f.profileWrites == 1 && f.markerWrites == 1, "Drift overwritten");
        });
        test("preimage drift fails before write", f -> {
            f.plan(); f.current.getAttribute("username").setDisplayName("pre-apply-change");
            reject(() -> f.apply(false)); check(f.profileWrites == 0 && f.markerWrites == 0, "Preimage overwritten");
        });
        test("unapproved hash and invalid backup fail closed", f -> {
            f.plan(); var flag = (com.fasterxml.jackson.databind.node.ObjectNode)f.flag(); flag.put("post_sha256", "f".repeat(64));
            reject(() -> ProfileMigration.process(f.session,"apply-v1",flag,f.directory,false));
            Files.writeString(f.directory.resolve("plan-v1.json"), "{}");
            reject(() -> ProfileMigration.process(f.session,"apply-v1",flag,f.directory,false));
            check(f.profileWrites == 0, "Invalid plan applied");
        });
        test("failed setter never records success marker", f -> {
            f.plan(); f.failSet = true; reject(() -> f.apply(false));
            check(f.markerWrites == 0 && f.profileWrites == 0, "Failure recorded success");
        });
        test("read-only commit verification cannot create migration", f -> {
            f.plan(); reject(() -> f.apply(true)); check(f.profileWrites == 0, "Verification wrote config");
        });
        test("realm and authentication guards preserve settings", f -> {
            f.realmName = "master"; reject(f::plan); f.realmName = "pajio";
            f.registration = true; reject(f::plan); f.registration = false;
            f.emailUsername = true; reject(f::plan); f.emailUsername = false;
            f.verifyEmail = true; reject(f::plan); f.verifyEmail = false;
            f.verify.setEnabled(false); reject(f::plan);
            check(f.profileWrites == 0 && f.markerWrites == 0, "Guard failure wrote config");
        });
        test("existing marker attributes require separate review", f -> {
            f.current.getAttributes().add(new UPAttribute("pajio_registration_id")); reject(f::plan);
        });
        test("root flag guard and symlink guard", f -> {
            Path flag = f.directory.resolve("flag.json"); Files.writeString(flag, "{\"mode\":\"plan-v1\",\"realm\":\"pajio\"}");
            // Under /tmp this must fail even when tests run as root; ancestors are writable.
            reject(() -> ProfileMigration.activation(flag,"plan-v1"));
            Path linked = f.directory.resolve("linked.json"); Files.createSymbolicLink(linked, flag);
            reject(() -> ProfileMigration.read(linked,4096));
        });
        System.out.println("ProfileMigration tests passed: " + passed);
    }
}
