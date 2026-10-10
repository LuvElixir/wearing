package io.pajio.cleanup;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.Set;
import java.util.TreeSet;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.models.utils.KeycloakModelUtils;
import org.keycloak.userprofile.UserProfileProvider;
import org.keycloak.util.JsonSerialization;

final class QACleanup {
    private QACleanup() {}
    static final String MARKER = "pajio.qa-cleanup.v1";
    static final ObjectMapper JSON = new ObjectMapper();
    private static final Set<PosixFilePermission> PRIVATE = PosixFilePermissions.fromString("rw-------");
    static String sha(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException("sha_unavailable"); }
    }
    static void require(boolean valid, String code) { if (!valid) throw new IllegalStateException(code); }
    static JsonNode canonical(JsonNode value) {
        if (value.isObject()) {
            var sorted = JSON.createObjectNode(); var names = new TreeSet<String>();
            value.fieldNames().forEachRemaining(names::add);
            for (String name : names) sorted.set(name, canonical(value.get(name)));
            return sorted;
        }
        if (value.isArray()) { var array = JSON.createArrayNode(); value.forEach(v -> array.add(canonical(v))); return array; }
        return value;
    }
    static byte[] bytes(Object value) throws IOException {
        return JSON.writeValueAsBytes(canonical(JSON.readTree(JsonSerialization.writeValueAsBytes(value))));
    }
    static void noSymlink(Path path) throws IOException {
        for (Path part = path.toAbsolutePath(); part != null; part = part.getParent())
            require(!Files.isSymbolicLink(part), "symlink_denied");
    }
    static JsonNode read(Path path, int max) throws IOException {
        noSymlink(path);
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && Files.size(path) <= max, "file_invalid");
        try (var stream = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] data = stream.readNBytes(max + 1);
            require(data.length <= max, "file_too_large");
            return JSON.readTree(data);
        }
    }
    static void privateDirectory(Path directory) throws IOException {
        noSymlink(directory);
        require(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS), "private_directory_missing");
        require(Files.getPosixFilePermissions(directory).equals(PosixFilePermissions.fromString("rwx------")), "private_directory_permissions");
        require(Files.getOwner(directory).getName().equals(System.getProperty("user.name")), "private_directory_owner");
    }
    static void immutable(Path path, JsonNode value) throws IOException {
        byte[] content = bytes(value);
        if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            require(Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS).equals(PRIVATE), "private_file_permissions");
            require(MessageDigest.isEqual(content, bytes(read(path, 1024 * 1024))), "private_file_drift");
            return;
        }
        try (FileChannel file = FileChannel.open(path, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PRIVATE))) {
            var buffer = ByteBuffer.wrap(content); while (buffer.hasRemaining()) file.write(buffer);
            file.force(true);
        }
        try (FileChannel parent = FileChannel.open(path.getParent(), StandardOpenOption.READ)) { parent.force(true); }
    }
    static Set<String> fields(JsonNode value) {
        var result = new HashSet<String>(); value.fieldNames().forEachRemaining(result::add); return result;
    }
    static JsonNode activation(Path flag, String mode) throws IOException {
        noSymlink(flag);
        for (Path path = flag.toAbsolutePath(); path != null; path = path.getParent()) {
            require(((Number)Files.getAttribute(path, "unix:uid", LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "activation_not_root_owned");
            var permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
            require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "activation_writable_by_others");
        }
        require(((Number)Files.getAttribute(flag, "unix:nlink", LinkOption.NOFOLLOW_LINKS)).intValue() == 1, "activation_hardlink");
        JsonNode value = read(flag, 8192);
        flagContract(value, mode);
        return value;
    }
    static void flagContract(JsonNode flag, String mode) {
        var expected = new HashSet<>(Set.of("mode", "realm", "subjects", "controller_inventory_sha256", "controller_fence_sha256"));
        if (mode.equals("apply-v1")) expected.addAll(Set.of("plan_sha256", "accounts"));
        require(Set.of("plan-v1", "apply-v1").contains(mode) && flag.isObject() && fields(flag).equals(expected)
            && mode.equals(flag.path("mode").asText()) && "pajio".equals(flag.path("realm").asText()), "flag_contract");
        for (String key : Set.of("controller_inventory_sha256", "controller_fence_sha256"))
            require(flag.path(key).asText().matches("[a-f0-9]{64}"), "controller_evidence_hash");
        var subjects = flag.path("subjects"); var unique = new HashSet<String>();
        require(subjects.isArray() && subjects.size() == 3, "exact_three_qa_subjects_required");
        for (JsonNode subject : subjects)
            require(subject.isTextual() && subject.asText().matches("[A-Za-z0-9_-]{1,128}") && unique.add(subject.asText()), "subject_invalid");
        if (mode.equals("apply-v1")) {
            require(flag.path("plan_sha256").asText().matches("[a-f0-9]{64}"), "plan_hash_invalid");
            var accounts = flag.path("accounts"); var names = new HashSet<String>(); var ids = new HashSet<String>();
            require(accounts.isArray() && accounts.size() == 3, "accounts_invalid");
            for (JsonNode account : accounts) require(account.isObject() && fields(account).equals(Set.of("subject", "username"))
                && unique.contains(account.path("subject").asText()) && ids.add(account.path("subject").asText())
                && account.path("username").asText().matches("[a-z][a-z0-9_.-]{3,63}") && names.add(account.path("username").asText()), "account_invalid");
        }
    }
    static JsonNode guards(KeycloakSession session, RealmModel realm) throws IOException {
        require(realm != null && "pajio".equals(realm.getName()), "wrong_realm");
        require(!realm.isRegistrationAllowed(), "self_registration_changed");
        var verify = realm.getRequiredActionProviderByAlias("VERIFY_PROFILE");
        require(verify != null && verify.isEnabled(), "verify_profile_changed");
        var client = realm.getClientByClientId("pajio-app");
        require(client != null && !client.isDirectAccessGrantsEnabled(), "direct_grants_changed");
        var profile = session.getProvider(UserProfileProvider.class).getConfiguration();
        require(profile != null, "profile_missing");
        var result = JSON.createObjectNode();
        result.put("login_theme", realm.getLoginTheme()).put("default_locale", realm.getDefaultLocale())
            .put("internationalization", realm.isInternationalizationEnabled()).put("profile_sha256", sha(bytes(profile)));
        var locales = result.putArray("supported_locales");
        try (var stream = realm.getSupportedLocalesStream()) { stream.sorted().forEach(locales::add); }
        return canonical(result);
    }
    static JsonNode account(KeycloakSession session, RealmModel realm, String subject) {
        UserModel user = session.users().getUserById(realm, subject);
        require(user != null && subject.equals(user.getId()), "qa_subject_not_found");
        require(user.getServiceAccountClientLink() == null && user.getFederationLink() == null, "nonlocal_or_service_user");
        require(user.getUsername() != null && user.getUsername().matches("[a-z][a-z0-9_.-]{3,63}"), "qa_username_invalid");
        // Reject direct or inherited administration roles, not only names.
        var management = realm.getClientByClientId("realm-management");
        require(management != null, "management_client_missing");
        try (var roles = management.getRolesStream()) { require(roles.noneMatch(user::hasRole), "administrative_user_refused"); }
        UserModel byName = session.users().getUserByUsername(realm, user.getUsername());
        require(byName != null && subject.equals(byName.getId()), "username_binding_changed");
        var value = JSON.createObjectNode().put("subject", subject).put("username", user.getUsername()).put("enabled", user.isEnabled());
        if (user.getCreatedTimestamp() != null) value.put("created_timestamp", user.getCreatedTimestamp());
        var actions = value.putArray("required_actions");
        try (var stream = user.getRequiredActionsStream()) { stream.sorted().forEach(actions::add); }
        return canonical(value);
    }
    static JsonNode targets(JsonNode flag) {
        var sorted = new TreeSet<String>(); flag.path("subjects").forEach(n -> sorted.add(n.asText()));
        var result = JSON.createArrayNode(); sorted.forEach(result::add); return result;
    }
    static JsonNode receipt(JsonNode plan) throws IOException {
        return JSON.createObjectNode().put("version", 1).put("state", "applied").put("deleted_count", 3)
            .put("plan_sha256", sha(bytes(plan))).put("realm_id_sha256", sha(plan.path("realm_id").asText().getBytes(java.nio.charset.StandardCharsets.UTF_8)));
    }
    static JsonNode process(KeycloakSession session, String mode, JsonNode flag, Path directory, boolean verifyOnly) {
        try {
            flagContract(flag, mode);
            RealmModel realm = session.realms().getRealmByName("pajio");
            require(realm != null && "pajio".equals(realm.getName()), "wrong_realm");
            session.getContext().setRealm(realm);
            JsonNode currentGuards = guards(session, realm);
            String marker = realm.getAttribute(MARKER);
            Path planFile = directory.resolve("plan-v1.json");
            if (mode.equals("plan-v1")) {
                require(marker == null, "cleanup_already_completed");
                var plan = JSON.createObjectNode().put("version", 1).put("realm", "pajio").put("realm_id", realm.getId());
                plan.set("subjects", targets(flag)); plan.set("guards", currentGuards);
                for (String key : Set.of("controller_inventory_sha256", "controller_fence_sha256")) plan.set(key, flag.get(key));
                var accounts = plan.putArray("accounts");
                for (JsonNode subject : plan.path("subjects")) accounts.add(account(session, realm, subject.asText()));
                immutable(planFile, plan);
                return JSON.createObjectNode().put("state", "planned").put("plan_sha256", sha(bytes(plan)));
            }
            JsonNode plan = read(planFile, 65536);
            require(Files.getPosixFilePermissions(planFile, LinkOption.NOFOLLOW_LINKS).equals(PRIVATE), "plan_permissions");
            require(flag.path("plan_sha256").asText().equals(sha(bytes(plan))) && plan.path("version").asInt() == 1
                && realm.getId().equals(plan.path("realm_id").asText()) && "pajio".equals(plan.path("realm").asText()), "unapproved_plan");
            for (String key : Set.of("controller_inventory_sha256", "controller_fence_sha256")) require(flag.path(key).equals(plan.path(key)), "controller_evidence_changed");
            require(targets(flag).equals(plan.path("subjects")) && currentGuards.equals(plan.path("guards")), "configuration_drift");
            for (JsonNode approved : flag.path("accounts")) {
                boolean match = false;
                for (JsonNode observed : plan.path("accounts")) if (observed.path("subject").equals(approved.path("subject"))
                    && observed.path("username").equals(approved.path("username"))) match = true;
                require(match, "account_not_approved");
            }
            JsonNode result = receipt(plan); String expectedMarker = sha(bytes(result));
            if (marker != null) {
                require(marker.equals(expectedMarker), "completed_marker_changed");
                for (JsonNode subject : plan.path("subjects")) require(session.users().getUserById(realm, subject.asText()) == null, "deleted_subject_reappeared");
                return result;
            }
            require(!verifyOnly, "commit_marker_missing");
            // Validate all three before removing any. Keycloak transaction rolls
            // back every deletion and the marker if any later step fails.
            for (JsonNode before : plan.path("accounts")) require(MessageDigest.isEqual(bytes(before), bytes(account(session, realm, before.path("subject").asText()))), "qa_account_drift");
            for (JsonNode before : plan.path("accounts")) {
                UserModel user = session.users().getUserById(realm, before.path("subject").asText());
                require(user != null && session.users().removeUser(realm, user), "qa_delete_failed");
            }
            require(guards(session, realm).equals(currentGuards), "unrelated_configuration_changed");
            realm.setAttribute(MARKER, expectedMarker);
            return result;
        } catch (IOException error) { throw new IllegalStateException("cleanup_io_failed"); }
    }
    static String run(KeycloakSessionFactory factory, String mode, Path flagFile, Path directory) throws IOException {
        JsonNode flag = activation(flagFile, mode); privateDirectory(directory);
        for (Path parent = directory.toAbsolutePath().getParent(); parent != null; parent = parent.getParent()) {
            require(((Number)Files.getAttribute(parent, "unix:uid", LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "data_parent_not_root_owned");
            var permissions = Files.getPosixFilePermissions(parent);
            require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "data_parent_writable");
        }
        Path lockFile = directory.resolve("cleanup-v1.lock"); noSymlink(lockFile);
        try (FileChannel channel = FileChannel.open(lockFile, Set.of(StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PRIVATE));
             var lock = channel.tryLock()) {
            require(lock != null, "cleanup_already_running");
            JsonNode result = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> process(session, mode, flag, directory, false));
            if (mode.equals("apply-v1")) {
                JsonNode verified = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> process(session, mode, flag, directory, true));
                require(result.equals(verified), "commit_verification_failed");
                immutable(directory.resolve("complete-v1.json"), result);
            }
            return sha(bytes(result));
        }
    }
}
