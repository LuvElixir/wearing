#!/usr/bin/env bash
# Builds and tests only; does not install or start Keycloak.
set -euo pipefail
umask 077
cleanup_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
keycloak_lib="${1:?Usage: build.sh keycloak-lib-directory new-output-directory}"
build_root="${2:?Output must be a new directory}"
test -f "$keycloak_lib/org.keycloak.keycloak-core-26.7.4.jar"
mkdir -- "$build_root"
build_root="$(CDPATH= cd -- "$build_root" && pwd)"
mkdir "$build_root/classes" "$build_root/tests"
javac --release 21 -encoding UTF-8 -Xlint:all -Werror -cp "$keycloak_lib/*" -d "$build_root/classes" "$cleanup_root"/src/io/pajio/cleanup/*.java
mkdir -p "$build_root/classes/META-INF/services"
cp "$cleanup_root/META-INF/services/org.keycloak.events.EventListenerProviderFactory" "$build_root/classes/META-INF/services/"
javac --release 21 -encoding UTF-8 -Xlint:all -Werror -cp "$keycloak_lib/*:$build_root/classes" -d "$build_root/tests" "$cleanup_root"/test/io/pajio/cleanup/*.java
java -ea -cp "$keycloak_lib/*:$build_root/classes:$build_root/tests" io.pajio.cleanup.QACleanupTest
env -u PAJIO_QA_CLEANUP java -ea -cp "$keycloak_lib/*:$build_root/classes:$build_root/tests" io.pajio.cleanup.QACleanupFactoryTest
for cleanup_mode in plan-v1 apply-v1 invalid; do
  PAJIO_QA_CLEANUP="$cleanup_mode" java -ea -cp "$keycloak_lib/*:$build_root/classes:$build_root/tests" io.pajio.cleanup.QACleanupFactoryTest
done
(cd "$build_root/classes" && jar --create --no-manifest --date=2026-10-10T00:00:00Z --file "$build_root/pajio-qa-cleanup.jar" META-INF io)
sha256sum "$build_root/pajio-qa-cleanup.jar"
