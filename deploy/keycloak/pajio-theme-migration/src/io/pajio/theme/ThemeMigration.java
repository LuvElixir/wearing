package io.pajio.theme;

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
import org.keycloak.models.utils.KeycloakModelUtils;
import org.keycloak.userprofile.UserProfileProvider;
import org.keycloak.util.JsonSerialization;

final class ThemeMigration {
    private ThemeMigration() {}
    static final String MARKER = "pajio.login-theme.v1";
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
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && Files.size(path) <= max && ((Number)Files.getAttribute(path, "unix:nlink", LinkOption.NOFOLLOW_LINKS)).intValue() == 1, "file_invalid");
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
        var expected = new HashSet<>(Set.of("mode", "realm", "theme_sha256"));
        if (mode.equals("apply-v1")) expected.add("plan_sha256");
        require(Set.of("plan-v1", "apply-v1").contains(mode) && flag.isObject() && fields(flag).equals(expected)
            && mode.equals(flag.path("mode").asText()) && "pajio".equals(flag.path("realm").asText()), "flag_contract");
        require(flag.path("theme_sha256").asText().matches("[a-f0-9]{64}"), "theme_hash_invalid");
        if (mode.equals("apply-v1")) require(flag.path("plan_sha256").asText().matches("[a-f0-9]{64}"), "plan_hash_invalid");
    }
    static final Set<String> THEME_FILES = Set.of("theme.properties", "resources/img/pajio-wordmark.svg", "resources/js/pajio.js",
        "resources/css/pajio-base.css", "resources/css/pajio-identity.css", "messages/messages_zh_CN.properties", "messages/messages_en.properties");
    static String themeHash(Path root) throws IOException {
        noSymlink(root);
        require(Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS), "theme_missing");
        var manifest = JSON.createObjectNode();
        try (var tree = Files.walk(root)) {
            for (Path path : tree.toList()) {
                noSymlink(path);
                require(((Number)Files.getAttribute(path,"unix:uid",LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "theme_not_root_owned");
                var permissions = Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS);
                require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "theme_writable_by_others");
                if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) continue;
                String relative = root.relativize(path).toString();
                require(THEME_FILES.contains(relative) && Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)
                    && ((Number)Files.getAttribute(path,"unix:nlink",LinkOption.NOFOLLOW_LINKS)).intValue() == 1 && Files.size(path) <= 262144, "theme_file_invalid");
                try (var stream = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
                    byte[] data = stream.readNBytes(262145); require(data.length <= 262144, "theme_file_too_large"); manifest.put(relative, sha(data));
                }
            }
        }
        require(fields(manifest).equals(THEME_FILES), "theme_file_set_changed");
        for (Path parent = root.getParent(); parent != null; parent = parent.getParent()) {
            require(((Number)Files.getAttribute(parent,"unix:uid",LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "theme_parent_not_root_owned");
            var permissions = Files.getPosixFilePermissions(parent, LinkOption.NOFOLLOW_LINKS);
            require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "theme_parent_writable");
        }
        return sha(bytes(manifest));
    }
    static JsonNode presentation(RealmModel realm) {
        var result = JSON.createObjectNode();
        result.put("login_theme", realm.getLoginTheme()).put("default_locale", realm.getDefaultLocale())
            .put("internationalization", realm.isInternationalizationEnabled());
        var locales = result.putArray("supported_locales");
        try (var stream = realm.getSupportedLocalesStream()) { stream.sorted().forEach(locales::add); }
        return canonical(result);
    }
    static JsonNode target(JsonNode before) {
        var result = JSON.createObjectNode().put("login_theme", "pajio").put("default_locale", "zh-CN").put("internationalization", true);
        var languages = new TreeSet<String>(); before.path("supported_locales").forEach(value -> languages.add(value.asText()));
        languages.addAll(Set.of("zh-CN", "en")); var locales = result.putArray("supported_locales"); languages.forEach(locales::add);
        return canonical(result);
    }
    static JsonNode guards(KeycloakSession session, RealmModel realm) throws IOException {
        require(realm != null && "pajio".equals(realm.getName()), "wrong_realm");
        require(!realm.isRegistrationAllowed(), "self_registration_changed");
        var verify = realm.getRequiredActionProviderByAlias("VERIFY_PROFILE");
        require(verify != null && verify.isEnabled(), "verify_profile_changed");
        var client = realm.getClientByClientId("pajio-app");
        require(client != null && !client.isDirectAccessGrantsEnabled(), "direct_grants_changed");
        var profile = session.getProvider(UserProfileProvider.class).getConfiguration(); require(profile != null, "profile_missing");
        var result = JSON.createObjectNode().put("profile_sha256", sha(bytes(profile))).put("verify_email", realm.isVerifyEmail())
            .put("reset_password", realm.isResetPasswordAllowed()).put("standard_flow", client.isStandardFlowEnabled())
            .put("security_headers_sha256", sha(bytes(realm.getBrowserSecurityHeaders())));
        try (var actions = realm.getRequiredActionProvidersStream()) {
            result.put("required_actions_sha256", sha(bytes(actions.sorted(java.util.Comparator.comparing(a -> a.getAlias())).toList())));
        }
        return canonical(result);
    }
    static JsonNode receipt(JsonNode plan) throws IOException {
        return JSON.createObjectNode().put("version", 1).put("state", "applied").put("plan_sha256", sha(bytes(plan)))
            .put("theme_sha256", plan.path("theme_sha256").asText()).put("presentation_sha256", sha(bytes(plan.path("after"))));
    }
    static JsonNode process(KeycloakSession session, String mode, JsonNode flag, Path directory, boolean verifyOnly) {
        try {
            flagContract(flag, mode);
            RealmModel realm = session.realms().getRealmByName("pajio");
            require(realm != null && "pajio".equals(realm.getName()), "wrong_realm"); session.getContext().setRealm(realm);
            JsonNode current = presentation(realm), guard = guards(session, realm);
            String marker = realm.getAttribute(MARKER); Path planFile = directory.resolve("plan-v1.json");
            if (mode.equals("plan-v1")) {
                require(marker == null && !verifyOnly, "migration_already_completed");
                var plan = JSON.createObjectNode().put("version", 1).put("realm", "pajio").put("realm_id", realm.getId()).put("theme_sha256", flag.path("theme_sha256").asText());
                plan.set("before", current); plan.set("after", target(current)); plan.set("guards", guard);
                immutable(planFile, plan);
                return JSON.createObjectNode().put("state", "planned").put("plan_sha256", sha(bytes(plan)));
            }
            JsonNode plan = read(planFile, 65536);
            require(Files.getPosixFilePermissions(planFile, LinkOption.NOFOLLOW_LINKS).equals(PRIVATE), "plan_permissions");
            require(flag.path("plan_sha256").asText().equals(sha(bytes(plan))) && plan.path("version").asInt() == 1
                && realm.getId().equals(plan.path("realm_id").asText()) && "pajio".equals(plan.path("realm").asText())
                && flag.path("theme_sha256").equals(plan.path("theme_sha256")) && target(plan.path("before")).equals(plan.path("after")), "unapproved_plan");
            require(guard.equals(plan.path("guards")), "security_configuration_drift");
            JsonNode result = receipt(plan); String expectedMarker = sha(bytes(result));
            if (marker != null) {
                require(marker.equals(expectedMarker) && current.equals(plan.path("after")), "completed_configuration_drift");
                return result; // Never overwrite settings after completion.
            }
            require(!verifyOnly && current.equals(plan.path("before")), "presentation_configuration_drift");
            var locales = new HashSet<String>(); plan.path("after").path("supported_locales").forEach(value -> locales.add(value.asText()));
            // The only presentation mutations; same Keycloak transaction as marker.
            realm.setLoginTheme("pajio"); realm.setDefaultLocale("zh-CN");
            realm.setInternationalizationEnabled(true); realm.setSupportedLocales(locales);
            require(presentation(realm).equals(plan.path("after")) && guards(session, realm).equals(guard), "postcondition_failed");
            realm.setAttribute(MARKER, expectedMarker);
            return result;
        } catch (IOException error) { throw new IllegalStateException("theme_migration_io_failed"); }
    }
    static String run(KeycloakSessionFactory factory, String mode, Path flagFile, Path directory) throws IOException {
        JsonNode flag = activation(flagFile, mode); privateDirectory(directory);
        for (Path parent = directory.toAbsolutePath().getParent(); parent != null; parent = parent.getParent()) {
            require(((Number)Files.getAttribute(parent,"unix:uid",LinkOption.NOFOLLOW_LINKS)).intValue() == 0, "data_parent_not_root_owned");
            var permissions = Files.getPosixFilePermissions(parent);
            require(!permissions.contains(PosixFilePermission.GROUP_WRITE) && !permissions.contains(PosixFilePermission.OTHERS_WRITE), "data_parent_writable");
        }
        require(flag.path("theme_sha256").asText().equals(themeHash(Path.of("/opt/keycloak-26.7.4/themes/pajio/login"))), "theme_artifact_drift");
        Path lockFile = directory.resolve("migration-v1.lock"); noSymlink(lockFile);
        try (FileChannel channel = FileChannel.open(lockFile, Set.of(StandardOpenOption.CREATE, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS), PosixFilePermissions.asFileAttribute(PRIVATE)); var lock = channel.tryLock()) {
            require(lock != null, "theme_migration_already_running");
            JsonNode result = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> process(session, mode, flag, directory, false));
            if (mode.equals("apply-v1")) {
                JsonNode verified = KeycloakModelUtils.runJobInTransactionWithResult(factory, session -> process(session, mode, flag, directory, true));
                require(result.equals(verified), "commit_verification_failed"); immutable(directory.resolve("complete-v1.json"), result);
            }
            return sha(bytes(result));
        }
    }
}
