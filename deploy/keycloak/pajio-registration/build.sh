#!/usr/bin/env bash
# Compile/test only. Never copies to a Keycloak installation or starts/rebuilds a server.
set -euo pipefail
umask 077
provider_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
keycloak_lib="${1:?Usage: build.sh /path/to/keycloak/lib/lib/main [new-output-directory]}"
if [[ ! -f "$keycloak_lib/org.keycloak.keycloak-core-26.7.4.jar" ]]; then
  echo 'Expected Keycloak 26.7.4 runtime jars.' >&2
  exit 2
fi
if [[ -n "${2:-}" ]]; then
  build_root="$2"
  mkdir -- "$build_root"
else
  build_root="$(mktemp -d "${TMPDIR:-/tmp}/pajio-registration-build.XXXXXXXX")"
fi
build_root="$(CDPATH= cd -- "$build_root" && pwd)"
mkdir "$build_root/classes" "$build_root/tests"
javac --release 21 -encoding UTF-8 -Xlint:all -Werror -cp "$keycloak_lib/*" \
  -d "$build_root/classes" "$provider_root"/src/io/pajio/identity/*.java
cp -R "$provider_root/META-INF" "$build_root/classes/"
javac --release 21 -encoding UTF-8 -Xlint:all -Werror -cp "$keycloak_lib/*:$build_root/classes" \
  -d "$build_root/tests" "$provider_root"/test/io/pajio/identity/*.java
java -ea -cp "$keycloak_lib/*:$build_root/classes:$build_root/tests" io.pajio.identity.RegistrationResourceTest
(cd "$build_root/classes" && jar --create --no-manifest --date=2026-10-10T00:00:00Z \
  --file "$build_root/pajio-registration.jar" META-INF io)
sha256sum "$build_root/pajio-registration.jar"
printf 'Artifact: %s/pajio-registration.jar\n' "$build_root"
