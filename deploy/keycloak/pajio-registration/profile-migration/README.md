# Pajio realm profile migration v1

This is a separate, one-time startup provider with no HTTP resource. It registers for `PostMigrationEvent` through the supported provider factory API, then uses `KeycloakModelUtils.runJobInTransactionWithResult` and `UserProfileProvider`. No administrative login, bootstrap administrator, MFA reset or database SQL is involved.

**Default is disabled.** Both `PAJIO_PROFILE_MIGRATION` and a root-owned `/etc/pajio/profile-migration-v1.json` must agree. Only `plan-v1` and `apply-v1` are accepted. All flag ancestors must be root-owned, not writable by group/others, and nonsymlinks. The flag may be 0640 root:Keycloak-service-group; it must be readable by the actual service user. It contains configuration hashes, not credentials.

Pre-create `/var/lib/pajio/profile-migration` as mode **0700**, owned by the actual Keycloak service user. Its ancestors must be root-owned, not group/other-writable, and nonsymlinks. The service's systemd write restrictions must allow this precise directory. Backup, lock and completion files are 0600. No paths or permissions are broadened by this provider.

## Plan

Set the process environment to `PAJIO_PROFILE_MIGRATION=plan-v1` and the flag to exactly:

```json
{"mode":"plan-v1","realm":"pajio"}
```

At the next reviewed startup it reads only realm `pajio` and requires self-registration disabled, email-as-username disabled, verify-email disabled, and `VERIFY_PROFILE` enabled. It does not change those settings. It creates `plan-v1.json` in the private directory with the full original profile, transformed candidate, realm ID and canonical pre/post SHA-256 hashes. The original profile is captured inside the read transaction, written with `CREATE_NEW`, fsynced together with its directory, and never overwritten. Repeating plan requires exact same content; drift or partial files stop the migration.

The transform removes `required` only from email/firstName/lastName, keeps the remaining profile configuration, and declares registration ID/fingerprint attributes admin-only. Existing registration attribute definitions are rejected for manual review. Required custom fields remain unchanged and may still trigger a profile prompt; review them before approving. Password remains a credential, not a user-profile attribute.

## Apply after review

Inspect the private plan diff. Replace the root-owned flag atomically with:

```json
{
  "mode":"apply-v1",
  "realm":"pajio",
  "realm_id":"exact realm_id from reviewed plan",
  "pre_sha256":"exact pre_sha256 from reviewed plan",
  "post_sha256":"exact post_sha256 from reviewed plan"
}
```

Set the environment to `PAJIO_PROFILE_MIGRATION=apply-v1` for the reviewed restart. Apply validates the approval, plan hashes, deterministic transform, realm ID, current profile preimage and authentication guards before writing. It changes only the user-profile configuration and the `pajio.profile-migration.v1` realm marker, in one Keycloak transaction. A second transaction verifies committed state before the private `complete-v1.json` receipt is written. A crash after commit but before receipt is safe: the existing marker/profile match is verified without a second write.

When enabled on later startups, a completed migration checks the pinned hash and authentication guards. Later administrator changes cause failure; they are **never overwritten**. Disable/remove this one-time provider's environment after acceptance if later profile edits should be permitted. The private backup must remain available for a separately reviewed rollback; this provider does not automatically restore old data.

Use this only on the current single Keycloak control node under maintenance, with registration held closed and no concurrent administrative profile changes. The file lock serializes this host's runs; it is not a multi-node distributed migration lock. Any failure propagates before Keycloak bootstrap completes. Logs contain success/failure plus hashes only; no profile content or stack cause is logged by this provider.

## Verification and remaining acceptance

Build without installation:

```sh
bash build.sh /opt/keycloak-26.7.4/lib/lib/main /tmp/new-unique-profile-build
```

The build uses the actual Keycloak 26.7.4 SDK and Java release 21, `-Xlint:all -Werror`. Eleven test groups cover the bundled upstream profile, retained fields, private immutable backup, apply/verify/repeat, preimage drift, later-admin drift, unapproved hash, failed writes, authentication guards, existing marker attributes, root ownership and symlink checks. Four separate JVM runs verify unset/plan/apply/invalid startup environment behavior. Storage and realm objects are synthetic proxies; no actual database or service is mutated. Tests assert that unexpected realm/authentication methods are never called.

Not yet verified by this work: live Quarkus discovery, a real database commit/rollback, actual service-user file permissions, and real OIDC first login after migration. These must be checked during root's guarded deployment. The public registration extension remains independently scoped and independently deployable.

Frozen candidate built 2026-10-10 with `javac 21.0.12.1`:

- Control host artifact: `/tmp/pajio-profile-artifact-20261010d/pajio-profile-migration.jar`
- SHA-256: `5efd9c42b5f3c5ae36c4e4fc75be371cc2e9cb1fc9f51ba028bd0049a051ab7e`
- Eleven core and four startup-gate test groups passed. No deployment or live realm mutation performed by this task.

Primary implementation references:

- [26.7.4 startup publishes PostMigrationEvent before bootstrap completion](https://github.com/keycloak/keycloak/blob/26.7.4/services/src/main/java/org/keycloak/services/resources/KeycloakApplication.java)
- [26.7.4 provider factory initialization and synchronous event dispatch](https://github.com/keycloak/keycloak/blob/26.7.4/services/src/main/java/org/keycloak/services/DefaultKeycloakSessionFactory.java)
- [UserProfileProvider configuration API](https://www.keycloak.org/docs-api/latest/javadocs/org/keycloak/userprofile/UserProfileProvider.html)
- [26.7.4 profile verification](https://github.com/keycloak/keycloak/blob/26.7.4/services/src/main/java/org/keycloak/authentication/requiredactions/VerifyUserProfile.java)
