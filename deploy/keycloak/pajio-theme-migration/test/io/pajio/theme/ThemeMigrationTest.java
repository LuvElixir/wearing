package io.pajio.theme;

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
import org.keycloak.representations.userprofile.config.UPConfig;
import org.keycloak.userprofile.UserProfileProvider;

public final class ThemeMigrationTest {
    private ThemeMigrationTest() {}
    private static int passed;
    private static void check(boolean value,String message) { if (!value) throw new AssertionError(message); }
    private static Object unexpected(String name) { throw new AssertionError("Unexpected SDK access: " + name); }
    private static <T> T stub(Class<T> type, InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[]{type}, handler));
    }
    private interface Action {void run() throws Exception;}
    private static void reject(Action action) throws Exception {
        try { action.run(); } catch (IllegalStateException expected) { return; }
        throw new AssertionError("Expected rejection");
    }
    private static final class Fixture implements AutoCloseable {
        final Path directory = Files.createTempDirectory("pajio-theme-sdk-test-", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        final Map<String,String> markers = new HashMap<>();
        final Set<String> locales = new HashSet<>(Set.of("en","ja"));
        final RequiredActionProviderModel verify = new RequiredActionProviderModel();
        String realmName="pajio", theme="previous", locale="en";
        boolean registration, directGrants, internationalization, verifyEmail, resetPassword;
        int writes;
        final KeycloakSession session;
        Fixture() throws IOException {
            verify.setAlias("VERIFY_PROFILE");verify.setEnabled(true);
            ClientModel client = stub(ClientModel.class, (p,m,a) -> switch(m.getName()) {
                case "isDirectAccessGrantsEnabled" -> directGrants;
                case "isStandardFlowEnabled" -> true;
                default -> unexpected(m.getName());
            });
            RealmModel realm = stub(RealmModel.class, (p,m,a) -> switch(m.getName()) {
                case "getName" -> realmName;
                case "getId" -> "synthetic-realm";
                case "isRegistrationAllowed" -> registration;
                case "isVerifyEmail" -> verifyEmail;
                case "isResetPasswordAllowed" -> resetPassword;
                case "getBrowserSecurityHeaders" -> Map.of("contentSecurityPolicy","strict");
                case "getRequiredActionProviderByAlias" -> {check("VERIFY_PROFILE".equals(a[0]),"Wrong action");yield verify;}
                case "getRequiredActionProvidersStream" -> Stream.of(verify);
                case "getClientByClientId" -> {check("pajio-app".equals(a[0]),"Wrong client");yield client;}
                case "getLoginTheme" -> theme;
                case "getDefaultLocale" -> locale;
                case "isInternationalizationEnabled" -> internationalization;
                case "getSupportedLocalesStream" -> locales.stream();
                case "getAttribute" -> markers.get((String)a[0]);
                case "setAttribute" -> {check(ThemeMigration.MARKER.equals(a[0]),"Unrelated marker");markers.put((String)a[0],(String)a[1]);writes++;yield null;}
                case "setLoginTheme" -> {theme=(String)a[0];writes++;yield null;}
                case "setDefaultLocale" -> {locale=(String)a[0];writes++;yield null;}
                case "setInternationalizationEnabled" -> {internationalization=(boolean)a[0];writes++;yield null;}
                case "setSupportedLocales" -> {locales.clear();for(Object entry:(Set<?>)a[0])locales.add((String)entry);writes++;yield null;}
                default -> unexpected(m.getName()); // Any security/user mutation fails this test.
            });
            RealmProvider realms = stub(RealmProvider.class,(p,m,a)->{check(m.getName().equals("getRealmByName")&&"pajio".equals(a[0]),"Wrong realm");return realm;});
            KeycloakContext context = stub(KeycloakContext.class,(p,m,a)->{check(m.getName().equals("setRealm")&&a[0]==realm,"Wrong context");return null;});
            UserProfileProvider profile = stub(UserProfileProvider.class,(p,m,a)->m.getName().equals("getConfiguration")?new UPConfig():unexpected(m.getName()));
            session = stub(KeycloakSession.class,(p,m,a)->switch(m.getName()) {
                case "realms" -> realms;
                case "getContext" -> context;
                case "getProvider" -> {check(a[0]==UserProfileProvider.class,"Wrong provider");yield profile;}
                default -> unexpected(m.getName()); // No UserProvider is accessible.
            });
        }
        JsonNode flag(String mode) throws IOException {
            var flag=ThemeMigration.JSON.createObjectNode().put("mode",mode).put("realm","pajio").put("theme_sha256","a".repeat(64));
            if(mode.equals("apply-v1"))flag.put("plan_sha256",ThemeMigration.sha(ThemeMigration.bytes(ThemeMigration.read(directory.resolve("plan-v1.json"),65536))));
            return flag;
        }
        JsonNode plan() throws IOException {return ThemeMigration.process(session,"plan-v1",flag("plan-v1"),directory,false);}
        JsonNode apply(boolean verifyOnly) throws IOException {return ThemeMigration.process(session,"apply-v1",flag("apply-v1"),directory,verifyOnly);}
        public void close() throws IOException {try(var paths=Files.list(directory)){for(Path path:paths.toList())Files.delete(path);}Files.delete(directory);}
    }
    private interface Case {void run(Fixture fixture) throws Exception;}
    private static void test(String name,Case action) throws Exception {try(Fixture fixture=new Fixture()){action.run(fixture);passed++;System.out.println("PASS "+name);}}
    public static void main(String[] args) throws Exception {
        test("plan is immutable private and mutation free",f->{check(f.plan().equals(f.plan()),"Plan changed");check(f.writes==0,"Plan mutated");check(Files.getPosixFilePermissions(f.directory.resolve("plan-v1.json")).equals(PosixFilePermissions.fromString("rw-------")),"Private plan");});
        test("four presentation fields only existing locales retained and repeat read only",f->{f.plan();JsonNode result=f.apply(false);check(f.theme.equals("pajio")&&f.locale.equals("zh-CN")&&f.internationalization&&f.locales.equals(Set.of("en","ja","zh-CN")),"Target differs");check(f.writes==5,"Unexpected mutations");check(result.equals(f.apply(true))&&result.equals(f.apply(false))&&f.writes==5,"Replay mutated");});
        test("wrong realm or security policy fails closed",f->{f.realmName="master";reject(f::plan);f.realmName="pajio";f.registration=true;reject(f::plan);f.registration=false;f.directGrants=true;reject(f::plan);f.directGrants=false;f.verify.setEnabled(false);reject(f::plan);check(f.writes==0,"Guard mutated");});
        test("presentation drift before apply never overwritten",f->{f.plan();f.locales.add("de");reject(()->f.apply(false));check(f.locales.contains("de")&&f.writes==0,"Drift overwritten");});
        test("security drift before apply rejected",f->{f.plan();f.verifyEmail=true;reject(()->f.apply(false));check(f.writes==0,"Security changed");});
        test("required action drift rejected",f->{f.plan();f.verify.setDefaultAction(true);reject(()->f.apply(false));check(f.writes==0,"Action overwritten");});
        test("wrong plan or artifact hash rejected",f->{f.plan();var flag=(com.fasterxml.jackson.databind.node.ObjectNode)f.flag("apply-v1");flag.put("plan_sha256","f".repeat(64));reject(()->ThemeMigration.process(f.session,"apply-v1",flag,f.directory,false));flag.put("plan_sha256",f.flag("apply-v1").path("plan_sha256").asText());flag.put("theme_sha256","b".repeat(64));reject(()->ThemeMigration.process(f.session,"apply-v1",flag,f.directory,false));check(f.writes==0,"Unapproved changes");});
        test("postcommit verify cannot initiate mutation",f->{f.plan();reject(()->f.apply(true));check(f.writes==0,"Verification mutated");});
        test("completed drift does not reset settings",f->{f.plan();f.apply(false);f.theme="newer_theme";reject(()->f.apply(false));check(f.theme.equals("newer_theme")&&f.writes==5,"New theme overwritten");});
        test("completed marker mismatch rejected",f->{f.plan();f.apply(false);f.markers.put(ThemeMigration.MARKER,"foreign");reject(()->f.apply(false));check(f.writes==5,"Marker overwritten");});
        test("unknown root flag field refused",f->{var flag=(com.fasterxml.jackson.databind.node.ObjectNode)f.flag("plan-v1");flag.put("disable_mfa",true);reject(()->ThemeMigration.flagContract(flag,"plan-v1"));check(f.writes==0,"Foreign instruction");});
        test("symlink and untrusted activation refused",f->{Path flag=f.directory.resolve("flag.json");Files.write(flag,ThemeMigration.bytes(f.flag("plan-v1")));reject(()->ThemeMigration.activation(flag,"plan-v1"));Path link=f.directory.resolve("link");Files.createSymbolicLink(link,flag);reject(()->ThemeMigration.read(link,8192));});
        System.out.println("ThemeMigration tests passed: "+passed);
    }
}
