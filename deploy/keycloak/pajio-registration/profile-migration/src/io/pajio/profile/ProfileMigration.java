package io.pajio.profile;

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
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.models.RealmModel;
import org.keycloak.models.utils.KeycloakModelUtils;
import org.keycloak.representations.userprofile.config.UPAttribute;
import org.keycloak.representations.userprofile.config.UPAttributePermissions;
import org.keycloak.representations.userprofile.config.UPConfig;
import org.keycloak.userprofile.UserProfileProvider;
import org.keycloak.util.JsonSerialization;

final class ProfileMigration {
    private ProfileMigration() {}
    static final String MARKER = "pajio.profile-migration.v1";
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
    static UPConfig transform(UPConfig original) throws IOException {
        UPConfig result = JsonSerialization.readValue(JsonSerialization.writeValueAsBytes(original), UPConfig.class);
        require(result.getAttributes() != null, "attributes_missing");
        Set<String> names = new HashSet<>();
        for (UPAttribute attribute : result.getAttributes()) {
            require(attribute != null && attribute.getName() != null && names.add(attribute.getName()), "attributes_invalid");
            if (Set.of("email", "firstName", "lastName").contains(attribute.getName())) attribute.setRequired(null);
        }
        require(names.containsAll(Set.of("username", "email", "firstName", "lastName")), "core_attributes_missing");
        for (var item : Map.of("pajio_registration_id", 32, "pajio_registration_fingerprint", 64).entrySet().stream().sorted(Map.Entry.comparingByKey()).toList()) {
            require(!names.contains(item.getKey()), "registration_attribute_exists");
            var attribute = new UPAttribute(item.getKey(), new UPAttributePermissions(Set.of("admin"), Set.of("admin")));
            attribute.setValidations(Map.of("length", Map.of("min", item.getValue(), "max", item.getValue()),
                "pattern", Map.of("pattern", "[a-f0-9]{" + item.getValue() + "}")));
            result.getAttributes().add(attribute);
        }
        return result;
    }
    static void realmGuards(RealmModel realm) {
        require(realm != null && "pajio".equals(realm.getName()), "wrong_realm");
        require(!realm.isRegistrationAllowed(), "self_registration_must_remain_disabled");
        require(!realm.isRegistrationEmailAsUsername() && !realm.isVerifyEmail(), "email_login_prerequisites");
        var verify = realm.getRequiredActionProviderByAlias("VERIFY_PROFILE");
        require(verify != null && verify.isEnabled(), "verify_profile_must_remain_enabled");
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
    static JsonNode activation(Path flag, String mode) throws IOException {
        noSymlink(flag);
        require(((Number)Files.getAttribute(flag, "unix:uid", LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "flag_not_root_owned");
        for (Path parent = flag.toAbsolutePath().getParent(); parent != null; parent = parent.getParent()) {
            require(((Number)Files.getAttribute(parent, "unix:uid", LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "flag_parent_not_root_owned");
            var parentPermissions = Files.getPosixFilePermissions(parent);
            require(!parentPermissions.contains(PosixFilePermission.GROUP_WRITE) && !parentPermissions.contains(PosixFilePermission.OTHERS_WRITE), "flag_parent_writable_by_others");
        }
        var permissions = Files.getPosixFilePermissions(flag, LinkOption.NOFOLLOW_LINKS);
        require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "flag_writable_by_others");
        JsonNode value = read(flag, 4096);
        Set<String> expected = mode.equals("plan-v1") ? Set.of("mode", "realm") : Set.of("mode", "realm", "realm_id", "pre_sha256", "post_sha256");
        Set<String> fields = new HashSet<>(); value.fieldNames().forEachRemaining(fields::add);
        require(value.isObject() && fields.equals(expected) && mode.equals(value.path("mode").asText()) && "pajio".equals(value.path("realm").asText()), "flag_contract");
        if (mode.equals("apply-v1")) {
            require(value.path("pre_sha256").asText().matches("[a-f0-9]{64}") && value.path("post_sha256").asText().matches("[a-f0-9]{64}") && !value.path("realm_id").asText().isBlank(), "flag_hashes");
        }
        return value;
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
    static JsonNode process(KeycloakSession session, String mode, JsonNode flag, Path directory, boolean verifyOnly) {
        try {
            var realm = session.realms().getRealmByName("pajio"); realmGuards(realm);
            session.getContext().setRealm(realm);
            var profile = session.getProvider(UserProfileProvider.class);
            UPConfig current = profile.getConfiguration();
            require(current != null, "profile_missing");
            String currentHash = sha(bytes(current));
            String marker = realm.getAttribute(MARKER);
            Path planFile = directory.resolve("plan-v1.json");
            if (mode.equals("plan-v1")) {
                require(marker == null, "migration_already_completed");
                UPConfig candidate = transform(current);
                var plan = JSON.createObjectNode();
                plan.put("version", 1).put("realm", "pajio").put("realm_id", realm.getId())
                    .put("pre_sha256", currentHash).put("post_sha256", sha(bytes(candidate)));
                plan.set("before", JSON.readTree(bytes(current))); plan.set("after", JSON.readTree(bytes(candidate)));
                immutable(planFile, plan);
                return receipt(plan, "planned");
            }
            require(mode.equals("apply-v1"), "invalid_mode");
            JsonNode plan = read(planFile, 1024 * 1024);
            require(Files.getPosixFilePermissions(planFile).equals(PRIVATE), "plan_permissions");
            require(plan.path("version").asInt() == 1 && "pajio".equals(plan.path("realm").asText()), "plan_contract");
            for (String field : Set.of("realm_id", "pre_sha256", "post_sha256")) require(flag.path(field).equals(plan.path(field)), "plan_not_approved");
            require(realm.getId().equals(plan.path("realm_id").asText()), "realm_identity_changed");
            require(sha(bytes(plan.path("before"))).equals(plan.path("pre_sha256").asText()) && sha(bytes(plan.path("after"))).equals(plan.path("post_sha256").asText()), "plan_hash_invalid");
            UPConfig before = JsonSerialization.readValue(bytes(plan.path("before")), UPConfig.class);
            UPConfig after = transform(before);
            require(sha(bytes(after)).equals(plan.path("post_sha256").asText()), "plan_transform_changed");
            String expectedMarker = sha(bytes(receipt(plan, "applied")));
            if (marker != null) {
                require(marker.equals(expectedMarker) && currentHash.equals(plan.path("post_sha256").asText()), "completed_configuration_drift");
                return receipt(plan, "applied");
            }
            require(!verifyOnly, "commit_marker_missing");
            require(currentHash.equals(plan.path("pre_sha256").asText()), "preimage_changed");
            // Persisted together by Keycloak's request/job transaction; backup already fsynced by plan.
            profile.setConfiguration(after);
            require(sha(bytes(profile.getConfiguration())).equals(plan.path("post_sha256").asText()), "postimage_changed");
            realm.setAttribute(MARKER, expectedMarker);
            realmGuards(realm);
            return receipt(plan, "applied");
        } catch (IOException error) { throw new IllegalStateException("migration_io_failed"); }
    }
    static JsonNode receipt(JsonNode plan, String state) {
        var result = JSON.createObjectNode().put("version", 1).put("state", state);
        for (String key : Set.of("realm_id", "pre_sha256", "post_sha256")) result.set(key, plan.path(key));
        return canonical(result);
    }
    static String run(KeycloakSessionFactory factory, String mode, Path flagFile, Path directory) throws IOException {
        JsonNode flag = activation(flagFile, mode); privateDirectory(directory);
        for (Path parent = directory.toAbsolutePath().getParent(); parent != null; parent = parent.getParent()) {
            require(((Number)Files.getAttribute(parent, "unix:uid", LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "data_parent_not_root_owned");
            var permissions = Files.getPosixFilePermissions(parent);
            require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "data_parent_writable_by_others");
        }
        Path lockFile = directory.resolve("migration-v1.lock"); noSymlink(lockFile);
        try (FileChannel channel = FileChannel.open(lockFile, Set.of(StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PRIVATE));
             var lock = channel.tryLock()) {
            require(lock != null, "migration_already_running");
            JsonNode result = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> process(session, mode, flag, directory, false));
            if (mode.equals("apply-v1")) {
                // New transaction verifies persisted state after the application transaction committed.
                JsonNode verified = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> process(session, mode, flag, directory, true));
                require(result.equals(verified), "commit_verification_failed");
                immutable(directory.resolve("complete-v1.json"), result);
            }
            return sha(bytes(result));
        }
    }
}
