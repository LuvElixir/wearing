# Reviewed Pajio login presentation migration

Startup-only provider for Keycloak **26.7.4**. No REST endpoint, admin password grant, credential access, or change to authentication, registration, profile, client, user, or role policies. It changes exactly four Pajio realm presentation fields: `loginTheme=pajio`, `defaultLocale=zh-CN`, `internationalizationEnabled=true`, and existing supported languages **union** `{zh-CN,en}`. A transaction marker is its only other realm write.

Build and unit checks (no installation):

```sh
bash build.sh /opt/keycloak-26.7.4/lib/lib/main /tmp/new-theme-migration-build
python -m pytest -q test_prepare_flag.py
```

The Java build uses the actual pinned SDK and Java 21 with `-Xlint:all -Werror`. Twelve behavior checks and four startup checks use strict SDK interface proxies. They do not claim live database transaction or live browser verification. The Python checks cover private flag preparation and exact artifact binding.

## Review and deployment boundary

1. Finish the independent QA account cleanup first. Its guards include theme/locale, so **do not enable QA apply and theme apply together** or rely on listener ordering. Disable the prior migration's environment activation before this one.
2. Root reviews the seven files under `deploy/keycloak/pajio-theme/login`, the provider JAR, and the actual realm plan. The provider accepts exactly those seven theme files at `/opt/keycloak-26.7.4/themes/pajio/login`; additional files, symlinks, hardlinks, changed bytes, or writable/non-root ancestors fail closed. The theme directory must be readable to `pajio-idp`; root-owned directories `0755` and files `0644` are suitable. This directory contains no FTL override.
3. Prepare a **local**, exclusive `0600` plan flag; this helper does not install or execute anything:

```sh
python prepare-flag.py --theme-dir ../pajio-theme/login --output /private/review/theme-plan-flag.json
```

4. After a bounded deployment is authorized, preserve an independent IdP database backup and old theme/providers/generated-build/systemd preimages. Install the reviewed JAR, install the exact flag at `/etc/pajio/theme-migration-v1.json` (root:`pajio-idp`, `0640`), and prepare `/var/lib/pajio/theme-migration-v1` owned by `pajio-idp`, `0700`, under trusted root-owned ancestors. Add that directory to the service's `ReadWritePaths`. Set only `PAJIO_THEME_MIGRATION=plan-v1` for the reviewed restart. The startup `PostMigrationEvent` writes immutable private `plan-v1.json`; plan makes **zero realm writes**.
5. Inspect that plan privately: exact realm ID, theme artifact hash, all four before/after fields, preserved languages, and security/profile guard hashes. The provider requires self-registration disabled, `VERIFY_PROFILE` enabled, and the Pajio client's direct grants disabled. Generate an apply candidate from the private `0600` observed plan:

```sh
python prepare-flag.py --theme-dir ../pajio-theme/login \
  --observed-plan /private/review/theme-plan-v1.json --output /private/review/theme-apply-flag.json
```

6. Root separately approves the exact plan and apply candidate. Install that flag with `PAJIO_THEME_MIGRATION=apply-v1` for one reviewed restart. Apply checks artifact hash, canonical plan hash, realm ID, before-values and security guards. The four presentation setters and receipt marker commit in the same supported Keycloak transaction. A fresh transaction verifies the committed marker and after-values before fsyncing private `complete-v1.json`.
7. A completed apply rechecks marker/configuration rather than overwriting later changes. Unknown outcomes require reading the exact marker/plan/receipt before any action. Remove the activation environment after success; leaving an old activation enabled intentionally prevents a later, unreviewed theme artifact change. This provider is not a generic rollback endpoint. If rollback is necessary, use a separately reviewed exact preimage restoration. Public login/API readiness and a genuine OIDC browser/App login remain release acceptance requirements.

No public log contains realm IDs, account data, plan contents, or credentials: provider diagnostics contain hashes only. Local flags/plans are private review material. The plan is metadata, **not** a restorable database backup.

API references: [RealmModel](https://www.keycloak.org/docs-api/latest/javadocs/org/keycloak/models/RealmModel.html), [PostMigrationEvent](https://www.keycloak.org/docs-api/latest/javadocs/org/keycloak/models/utils/PostMigrationEvent.html). The installed **26.7.4** SDK compilation is authoritative for API compatibility; latest documentation can move ahead of that version.
