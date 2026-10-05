#!/usr/bin/env bash
# JitPack install step for Maven libraries.
# JitPack's image strips *.jar files, which breaks the Maven wrapper jar AND
# the bundled system mvn — so we install Maven via sdkman (already present,
# it provides the JDK) and build with it.
set -e
sdk install maven 3.9.11 < /dev/null || true
mvn -B -ntp install -DskipTests -Dgpg.skip
