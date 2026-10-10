package io.pajio.cleanup;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;
import org.keycloak.models.ClientModel;
import org.keycloak.models.KeycloakContext;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.RealmProvider;
import org.keycloak.models.RequiredActionProviderModel;
import org.keycloak.models.RoleModel;
import org.keycloak.models.UserModel;
import org.keycloak.models.UserProvider;
import org.keycloak.representations.userprofile.config.UPConfig;
import org.keycloak.userprofile.UserProfileProvider;

public final class QACleanupTest {
    private QACleanupTest() {}
    private static int passed;
    private static void check(boolean valid, String message) { if (!valid) throw new AssertionError(message); }
    private static Object unexpected(String name) { throw new AssertionError("Unexpected SDK call: " + name); }
    private static <T> T stub(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }
    private interface Action { void run() throws Exception; }
    private static void reject(Action action) throws Exception {
        try { action.run(); } catch (IllegalStateException expected) { return; }
        throw new AssertionError("Expected rejection");
    }
    private static final class Fixture implements AutoCloseable {
        final Path directory = Files.createTempDirectory("pajio-cleanup-sdk-test-", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        final Map<String,String> markers = new HashMap<>();
        final Map<String,String> names = new HashMap<>(Map.of("qa-a", "acceptance_a", "qa-b", "acceptance_b", "qa-c", "acceptance_c", "preserve", "real_person"));
        final Set<String> deleted = new HashSet<>();
        final RequiredActionProviderModel verify = new RequiredActionProviderModel();
        String realmName = "pajio", loginTheme = "previous", locale = "en", adminSubject, serviceSubject;
        boolean registration, directGrants, failDelete;
        int writes;
        final KeycloakSession session;
        Fixture() throws IOException {
            verify.setEnabled(true);
            RoleModel adminRole = stub(RoleModel.class, (p,m,a) -> unexpected(m.getName()));
            ClientModel management = stub(ClientModel.class, (p,m,a) -> m.getName().equals("getRolesStream") ? Stream.of(adminRole) : unexpected(m.getName()));
            ClientModel client = stub(ClientModel.class, (p,m,a) -> m.getName().equals("isDirectAccessGrantsEnabled") ? directGrants : unexpected(m.getName()));
            RealmModel realm = stub(RealmModel.class, (p,m,a) -> switch (m.getName()) {
                case "getName" -> realmName;
                case "getId" -> "synthetic-realm";
                case "isRegistrationAllowed" -> registration;
                case "getRequiredActionProviderByAlias" -> { check("VERIFY_PROFILE".equals(a[0]), "Wrong action"); yield verify; }
                case "getClientByClientId" -> "pajio-app".equals(a[0]) ? client : "realm-management".equals(a[0]) ? management : unexpected("client");
                case "getLoginTheme" -> loginTheme;
                case "getDefaultLocale" -> locale;
                case "isInternationalizationEnabled" -> false;
                case "getSupportedLocalesStream" -> Stream.of("en");
                case "getAttribute" -> markers.get((String)a[0]);
                case "setAttribute" -> { check(QACleanup.MARKER.equals(a[0]), "Other attribute changed"); writes++; markers.put((String)a[0], (String)a[1]); yield null; }
                default -> unexpected(m.getName());
            });
            RealmProvider realms = stub(RealmProvider.class, (p,m,a) -> { check(m.getName().equals("getRealmByName") && "pajio".equals(a[0]), "Wrong realm"); return realm; });
            KeycloakContext context = stub(KeycloakContext.class, (p,m,a) -> { check(m.getName().equals("setRealm") && a[0] == realm, "Wrong context"); return null; });
            UserProfileProvider profile = stub(UserProfileProvider.class, (p,m,a) -> m.getName().equals("getConfiguration") ? new UPConfig() : unexpected(m.getName()));
            UserProvider users = stub(UserProvider.class, (p,m,a) -> switch (m.getName()) {
                case "getUserById" -> user((String)a[1]);
                case "getUserByUsername" -> names.entrySet().stream().filter(e -> e.getValue().equals(a[1]) && !deleted.contains(e.getKey())).map(e -> user(e.getKey())).findFirst().orElse(null);
                case "removeUser" -> { check(a[0] == realm, "Wrong remove realm"); String id = ((UserModel)a[1]).getId(); check(Set.of("qa-a", "qa-b", "qa-c").contains(id), "Foreign deletion"); if (failDelete) yield false; yield deleted.add(id); }
                default -> unexpected(m.getName());
            });
            session = stub(KeycloakSession.class, (p,m,a) -> switch (m.getName()) {
                case "realms" -> realms;
                case "getContext" -> context;
                case "users" -> users;
                case "getProvider" -> { check(a[0] == UserProfileProvider.class, "Wrong provider"); yield profile; }
                default -> unexpected(m.getName());
            });
        }
        UserModel user(String id) {
            if (!names.containsKey(id) || deleted.contains(id)) return null;
            return stub(UserModel.class, (p,m,a) -> switch (m.getName()) {
                case "getId" -> id;
                case "getUsername" -> names.get(id);
                case "getServiceAccountClientLink" -> id.equals(serviceSubject) ? "client" : null;
                case "getFederationLink" -> null;
                case "isEnabled" -> true;
                case "getCreatedTimestamp" -> 42L;
                case "getRequiredActionsStream" -> Stream.empty();
                case "hasRole" -> id.equals(adminSubject);
                default -> unexpected(m.getName());
            });
        }
        JsonNode flag(String mode) throws IOException {
            var flag = QACleanup.JSON.createObjectNode().put("mode", mode).put("realm", "pajio")
                .put("controller_inventory_sha256", "a".repeat(64)).put("controller_fence_sha256", "b".repeat(64));
            flag.putArray("subjects").add("qa-a").add("qa-b").add("qa-c");
            if (mode.equals("apply-v1")) {
                JsonNode plan = QACleanup.read(directory.resolve("plan-v1.json"), 65536);
                flag.put("plan_sha256", QACleanup.sha(QACleanup.bytes(plan)));
                var accounts = flag.putArray("accounts");
                for (JsonNode user : plan.path("accounts")) accounts.addObject().put("subject", user.path("subject").asText()).put("username", user.path("username").asText());
            }
            return flag;
        }
        JsonNode plan() throws IOException { return QACleanup.process(session, "plan-v1", flag("plan-v1"), directory, false); }
        JsonNode apply(boolean verifyOnly) throws IOException { return QACleanup.process(session, "apply-v1", flag("apply-v1"), directory, verifyOnly); }
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
        test("plan immutable private and no mutations", f -> { check(f.plan().equals(f.plan()), "Plan changed"); check(f.writes == 0 && f.deleted.isEmpty(), "Plan mutated"); check(Files.getPosixFilePermissions(f.directory.resolve("plan-v1.json")).equals(PosixFilePermissions.fromString("rw-------")), "Private plan mode"); });
        test("exact subjects removed theme locale and real user preserved", f -> { f.plan(); JsonNode receipt = f.apply(false); check(receipt.equals(f.apply(true)) && receipt.equals(f.apply(false)), "Repeat must inspect"); check(f.deleted.equals(Set.of("qa-a", "qa-b", "qa-c")) && f.user("preserve") != null && f.writes == 1, "Deletion scope"); check(f.loginTheme.equals("previous") && f.locale.equals("en"), "Presentation changed"); });
        test("wrong realm registration direct grants and VERIFY_PROFILE refused", f -> { f.realmName = "master"; reject(f::plan); f.realmName = "pajio"; f.registration = true; reject(f::plan); f.registration = false; f.directGrants = true; reject(f::plan); f.directGrants = false; f.verify.setEnabled(false); reject(f::plan); check(f.deleted.isEmpty(), "Guard deleted"); });
        test("administrative or service user refused", f -> { f.adminSubject = "qa-a"; reject(f::plan); f.adminSubject = null; f.serviceSubject = "qa-c"; reject(f::plan); check(f.deleted.isEmpty(), "Privileged user deleted"); });
        test("username drift of third user detected before any removal", f -> { f.plan(); f.names.put("qa-c", "changed_name"); reject(() -> f.apply(false)); check(f.deleted.isEmpty(), "Partial deletion before validation"); });
        test("configuration drift refused without overwrite", f -> { f.plan(); f.loginTheme = "later_theme"; reject(() -> f.apply(false)); check(f.deleted.isEmpty() && f.loginTheme.equals("later_theme"), "Configuration overwritten"); });
        test("invalid approval hash or username refused", f -> { f.plan(); var flag = (com.fasterxml.jackson.databind.node.ObjectNode)f.flag("apply-v1"); flag.put("plan_sha256", "f".repeat(64)); reject(() -> QACleanup.process(f.session, "apply-v1", flag, f.directory, false)); flag.put("plan_sha256", f.flag("apply-v1").path("plan_sha256").asText()); ((com.fasterxml.jackson.databind.node.ObjectNode)flag.path("accounts").get(0)).put("username", "wrong_name"); reject(() -> QACleanup.process(f.session, "apply-v1", flag, f.directory, false)); check(f.deleted.isEmpty(), "Invalid approval deleted"); });
        test("missing user and failed remove do not mark complete", f -> { f.plan(); f.failDelete = true; reject(() -> f.apply(false)); check(f.writes == 0, "Failed delete completed"); f.failDelete = false; f.deleted.add("qa-a"); reject(() -> f.apply(false)); check(f.writes == 0, "Missing user adopted"); });
        test("commit verification cannot initiate deletion", f -> { f.plan(); reject(() -> f.apply(true)); check(f.deleted.isEmpty(), "Verification deleted"); });
        test("completed subject reappearance is never re-deleted", f -> { f.plan(); f.apply(false); f.deleted.remove("qa-a"); reject(() -> f.apply(false)); check(!f.deleted.contains("qa-a") && f.writes == 1, "Reappearance deleted"); });
        test("root flag and symlink safety", f -> { Path flag = f.directory.resolve("flag.json"); Files.write(flag, QACleanup.bytes(f.flag("plan-v1"))); reject(() -> QACleanup.activation(flag, "plan-v1")); Path link = f.directory.resolve("link"); Files.createSymbolicLink(link, flag); reject(() -> QACleanup.read(link,8192)); });
        System.out.println("QACleanup tests passed: " + passed);
    }
}
