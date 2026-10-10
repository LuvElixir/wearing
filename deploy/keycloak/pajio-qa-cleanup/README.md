# One-time QA account cleanup

Separate startup-only Keycloak 26.7.4 SPI. It exposes no REST endpoint and does not use an admin password grant, disable MFA, or broaden the registration broker. It **does not change theme, locale, profile, client, or authentication configuration**.

Build/tests (compilation only):

```
bash build.sh /opt/keycloak-26.7.4/lib/lib/main /tmp/new-qa-cleanup-build
```

The build uses the actual pinned Keycloak SDK with Java 21 and `-Werror`. Tests use strict SDK interface proxies, not a live Keycloak database. Production transaction behavior must be verified after a reviewed deployment.

1. Independently finish controller membership fencing and session revocation for the exact three QA accounts. `prepare-flag.py` validates the private original control inventory and fence receipt; it writes an exclusive local `0600` **plan** flag. It never installs or executes it. The control evidence is bound by SHA-256; the SPI does not access the controller database.
2. Only after reviewing the JAR and scope, install the flag at `/etc/pajio/qa-cleanup-v1.json`, root owned, non-writable by group/others (e.g. root:keycloak `0640`). Every ancestor must be root owned and non-writable by others. Prepare `/var/lib/pajio/qa-cleanup-v1` owned by the Keycloak service user, mode `0700`, under trusted root-owned ancestors. Enable `PAJIO_QA_CLEANUP=plan-v1` for one reviewed restart.
3. Plan mode looks up only the three approved subject IDs in realm `pajio` and writes an immutable `0600` `plan-v1.json`. It records observed usernames, creation times, enabled state, required actions, and configuration guard hashes. It never reads passwords or credential material. Review all three usernames/IDs against the original QA scope. Rejects missing, service, federated, or realm-management privileged users.
4. Use the private observed plan to generate a proposed **apply** flag. It binds the complete canonical plan hash, original evidence hashes, and exact observed `{subject, username}` pairs. Review and install this root-owned flag with `PAJIO_QA_CLEANUP=apply-v1` only when deletion is authorized. Preserve an independent IdP database backup before this irreversible QA deletion; the metadata plan is not a restorable account backup.
5. Apply rechecks all three accounts before any delete. All three `removeUser` calls and the receipt hash marker are one supported `runJobInTransactionWithResult` transaction. A second transaction checks the committed marker, all three absent IDs, and unchanged guards, then fsyncs the private `complete-v1.json`. A failed/unknown return never authorizes another independent delete. Restarting the same approved apply checks the marker/absence and writes a missing post-commit receipt without redoing deletion.
6. Remove the environment activation after success. A later account/configuration change is never overwritten. If completion is unknown, inspect exact marker/plan/receipt first. No rollback action silently recreates credentials or restores QA privileges.

The private flag supports exactly three unique subjects; it cannot select users by wildcard, username search, realm-wide enumeration, or count. Root must review the plan before apply. No user identifiers are hardcoded in this public source or printed to logs. Logs and public completion receipt contain hashes/counts only.
