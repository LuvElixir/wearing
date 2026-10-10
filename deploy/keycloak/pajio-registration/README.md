# Pajio create-only registration provider

Candidate for Keycloak **26.7.4 / Java 21**. This directory does not deploy anything. The broker remains responsible for validating and consuming the invitation, CSRF/origin checks, rate limiting, continuation binding and user-facing errors.

## Boundary and contract

The two synchronous endpoints are `POST /realms/pajio/pajio-registration/create` and `POST /realms/pajio/pajio-registration/inspect`. Authentication uses the fixed `/etc/pajio/registration-provider.key` file. The factory cannot select another key path; a package-private constructor exists only for isolated tests. Provision the file with a unique 64-character base64url key, owner readable by the Keycloak service and mode 0600. Do not put the key in this repository, environment dumps or URLs.

`create` accepts exactly `username`, `password`, `registration_id`, `fingerprint`; `inspect` accepts the same set without `password`. The broker must generate the registration ID and fingerprint; never trust client-supplied idempotency metadata. A matching retry returns the existing subject without writing credentials or attributes. A conflicting, disabled or service-account user returns `username_unavailable`. The provider has no update, reset, role, email-verification, delete or token-issuance operation. Partial credential failure marks the Keycloak request transaction rollback-only and reports `registration_unknown`; the broker must inspect the same intent before deciding how to retry.

Body size is bounded to 4096 bytes and only ASCII usernames matching `[a-z][a-z0-9_.-]{3,31}` are accepted. Password validation is 12–128 Unicode code points with no ISO control characters, plus the realm password policy. This matches Python `len`, including supplementary characters; the broker must also reject U+007F–U+009F controls. Success returns only subject/registration ID; responses are not cacheable. No request payload or credential logging is added.

Before deployment: block these paths at the public reverse proxy and allow the private broker route only. Preserve that block during Keycloak restart/build. Ensure realm defaults grant no administrative roles to new users. The independent provider key is narrower than an administrative token, but still allows creation of accounts and must remain server-only.

## Username/password-only first login

The bundled default user profile requires email, firstName and lastName for user-context validation. `VERIFY_PROFILE` checks that profile on login and asks for the missing fields. The correct candidate is to remove only these three attributes' `required` entries; retain validators, existing profile settings and the `VERIFY_PROFILE` action. Keep username configured. Also confirm `registrationEmailAsUsername=false`, `verifyEmail=false` and no other mandatory action/custom attribute that requires input. Optional email does not provide password recovery until a verified recovery channel is added.

The internal `pajio_registration_id` and `pajio_registration_fingerprint` attributes must be declared with **view/edit permissions only for admin**, never user. They are not profile prompts and have no `required` entry. This protects retry-matching metadata from Account Console edits. An administrative override still remains possible by design.

`prepare-user-profile.py` only creates a JSON candidate from a supplied existing profile. It does not call Keycloak or overwrite its input/output. It preserves unrelated attributes, validators, groups and policy; it refuses pre-existing registration attributes rather than guessing their semantics.

```sh
python3 prepare-user-profile.py existing-profile.json candidate-profile.json
python3 test_profile.py
```

Applying the candidate is a separate reviewed step: capture/hash the current realm profile, inspect the exact diff, compare the current profile before writing, retain a rollback copy, then test a newly created account through the real OIDC login and check that existing-account login still works. No production realm profile was read or changed during this review. First-login behavior is established from the versioned implementation and configuration, not yet a live acceptance result.

## Build and isolated verification

```sh
bash build.sh /opt/keycloak-26.7.4/lib/lib/main /tmp/new-unique-build-directory
```

The output directory must not exist. The script compiles with Java release 21, all warnings as errors, then runs the ten Java test groups against the actual runtime SDK and JSON/Response implementations with synthetic storage proxies. It writes a deterministic-timestamp JAR containing only the provider classes and discovery resources; tests and third-party libraries are excluded. It never copies to `providers/`, runs `kc.sh`, or restarts a service.

On 2026-10-10, the control host's `javac 21.0.12.1` and Keycloak 26.7.4 jars passed all ten groups; all three offline profile transformation tests also passed. Candidate artifact:

- Control host: `/tmp/pajio-registration-artifact-20261010d/pajio-registration.jar`
- SHA-256: `1a7cadd1b272605fd26e62fe008dfbe3378dfedc9d693eae3926bc20429827b4`
- No provider installation, Keycloak rebuild/restart, live registration or production profile mutation occurred.

Compile/review fixes: `UserModel` uses `getServiceAccountClientLink()`, not the nonexistent `isServiceAccount()`; the REST class has `jakarta.ws.rs.ext.Provider`; `META-INF/beans.xml` is an empty file. Actual `javap` inspection and compilation verified the API fix. Runtime route discovery still requires the separate deployment acceptance.

The independent [startup migration](profile-migration/README.md) is built as a separate JAR. It does not expand this provider's API.

## Primary references

- [Keycloak extension discovery and synchronous request lifecycle](https://www.keycloak.org/docs/latest/server_development/index.html#_extensions_rest)
- [Keycloak user-profile configuration and attribute permissions](https://www.keycloak.org/docs/latest/server_admin/index.html#user-profile)
- [26.7.4 default profile](https://github.com/keycloak/keycloak/blob/26.7.4/services/src/main/resources/org/keycloak/userprofile/config/keycloak-default-user-profile.json)
- [26.7.4 VerifyUserProfile trigger](https://github.com/keycloak/keycloak/blob/26.7.4/services/src/main/java/org/keycloak/authentication/requiredactions/VerifyUserProfile.java)
