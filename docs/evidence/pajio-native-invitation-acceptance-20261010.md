# Native invitation acceptance — 2026-10-10

The updated Release app was installed on the owner's connected iPhone Air
(iOS 27). Installation completed and strict code-signature verification passed.
The owner unlocked the phone for direct visual acceptance.

Verified on that physical phone:

- The Pajio welcome screen renders in dark appearance with native invitation
  entry and an existing-account option.
- Submitting an empty invitation produces an inline error and focus treatment;
  it does not open a web page.
- Switching to the existing-account option preserves the same visual selection
  treatment and presents the sign-in action.
- Existing-account sign-in opens the normal iOS authentication consent, then
  the production identity-provider login page at `id.pajio.luckyloading.com`.
- Closing that authentication view returns to the app normally.

No password, invitation, or real account was submitted in this UI check. This
does not establish successful signup, account ownership, Core chat, or provisioned
device access. Those require the capacity-backed invitation and live activation
acceptance.

The private source manifest is in
`.wearing/on-prem/20261009/native-provisioning-20261010/source-manifest.json`,
SHA-256 `fe4c47f645dc3f4257e4191d288cff701fc5a1ac49c92ca1b828062e1dab8c29`.
The twelve runtime source files were verified against the staged native build.

A separate generic iOS Release archive completed with `ARCHIVE SUCCEEDED` at
11:16 UTC. App Store export subsequently completed with `EXPORT SUCCEEDED`.
The exported IPA is 39,090,828 bytes, version 0.2.0 (build 1), SHA-256
`adde4d654cc8263a6a6606e1b57ef683dbd2f4926cebb7e343a06d58fdc11257`.
Its embedded distribution profile has `get-task-allow=false`,
`beta-reports-active=true`, and no registered-device list or enterprise grant.

The first upload attempt stopped before transfer because App Store Connect had
no app record for `io.luckyloading.wearing.mobile`. After the owner signed in,
the Pajio iOS record was created (Apple ID `6821325213`, SKU `pajio-ios`).
A second upload completed at 19:33:54 Asia/Shanghai with `Upload succeeded`
and `EXPORT SUCCEEDED`; Apple acknowledged that the package was processing.
This is upload evidence, not external testing approval or an installation link.

Xcode reported nonfatal missing dSYM warnings for the prebuilt React,
ReactNativeDependencies and hermesvm frameworks. The binary upload succeeded;
crash symbolication for those frameworks is not established by this receipt.

The owner filled the beta review contact directly in Safari. The beta
description identifies Pajio as an individual-developer, invitation-only test
product. Per the owner's latest direction, company operation, organization
membership conversion and the future product name are outside this release.
At that form-review checkpoint, a real, isolated reviewer login and a factual
privacy page were still required. The [privacy and support pages](pajio-auth-design-20261010/public-pages-release.md)
have since been published and checked publicly. A real reviewer login and
external-test submission remain outstanding. No review credentials have been
fabricated, no review was submitted, and no new agreement was accepted.

Apple subsequently processed build 1 and displayed it in TestFlight. Its
missing encryption-information state was resolved through the build's Manage
dialog; the confirmed resulting state is **Ready to Submit**, expiring in
90 days. This does not mean external beta review was approved.

The encryption determination reviewed the staged build's Podfile.lock,
ExpoCrypto 57.0.3 iOS implementation (Apple CommonCrypto/CryptoKit), SecureStore
(system Keychain), PKCE SHA-256/randomness calls, and the remote viewer's
system WebKit `RTCPeerConnection`. No separately linked OpenSSL, BoringSSL,
libsodium, SQLCipher or native WebRTC implementation was present in that lock
file. The App Store Connect choice excludes proprietary and separately
implemented standard cryptography; it does not mean HTTPS or WebRTC is
unencrypted. The next build's app configuration now declares
`ITSAppUsesNonExemptEncryption=false` for this reviewed dependency set. Revisit
this determination if the shipped crypto implementation changes.

References: [Apple encryption guidance](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations)
and [documentation requirements](https://developer.apple.com/help/app-store-connect/reference/export-compliance-documentation-for-encryption/).

## Subsequent build 2 physical-device checkpoint

Pajio 0.2.0 build 2 passed `codesign --verify --deep --strict`. Its physical-device
installation and launch both succeeded, and Device Hub showed the updated native
invitation welcome screen on the owner's connected iPhone. Private receipts are
`build-result.json`, `device-install-v2-result.json`, and `device-launch-result.json`
under `.wearing/on-prem/20261009/native-personal-beta2-20261010/`.

This checkpoint does not extend the earlier build 1 TestFlight receipt to build 2.
Real invitation redemption, account creation, a confirmed three-environment
provisioning result, and remote access to the personal Linux and Android devices
remain unverified. Neither physical installation nor the welcome screen proves
that the service is ready for external users.

Build 2 physical-device interaction checks also confirmed empty-invite validation,
tab selection with input focus dismissed, and the native privacy link opening the
live personal-invitation privacy page in iPhone Safari, then returning to Pajio.
The welcome and privacy captures were retained privately with SHA-256
`4d9a2e8fd2d6524119efd722a36603d8e0bd3005450157d1e97e65ecd00f949c` and
`51efd5f7b7eaa25cfeed2124d0b039b6521e8dd8f068f09c6f91cffca86764b9`.
These checks do not prove an authenticated user session or device provisioning.

## Build 2 distribution and first real registration

Build 2 export and upload both completed successfully. Its exported IPA is
38,423,379 bytes, SHA-256
`4a7ffd14a6ff89a1dd061f6619da25a35cc7ca78373ec3da18857c0ed960ecf3`.
Apple acknowledged the upload at 21:19:05 Asia/Shanghai. App Store Connect
subsequently displayed version 0.2.0 build 2 as **Ready to Submit**, expiring in
90 days, and confirmed its association with the `Pajio 个人内测` internal group.
The group association is not an external beta approval or a tester installation.
No tester invitation email or external review submission was sent at this checkpoint.

The first capacity-backed invitation was issued once and delivered to the owner
privately. The owner completed native account and password creation on the
physical iPhone. The control database then confirmed one member, one private
ownership record, one bundle, and one activation for the intended tenant.
Device Hub showed the authenticated native provisioning screen: Core ready,
Linux preparing, Android pending. This verifies real invitation redemption and
entry into the activation flow; device readiness and remote control are separate
acceptance stages.
