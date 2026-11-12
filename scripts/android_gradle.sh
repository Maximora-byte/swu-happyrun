#!/usr/bin/env bash
# Official Gradle binary, checksum pinned from https://gradle.org/release-checksums/.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
cache="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/happyrun-gradle-8.9"
mkdir -p "$cache"
if [[ ! -x "$cache/gradle-8.9/bin/gradle" ]]; then
  curl --fail --location --retry 3 --proto '=https' --tlsv1.2     https://services.gradle.org/distributions/gradle-8.9-bin.zip -o "$cache/gradle.zip"
  echo "d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab  $cache/gradle.zip" | sha256sum -c -
  unzip -q -o "$cache/gradle.zip" -d "$cache"
fi
exec "$cache/gradle-8.9/bin/gradle" --no-daemon -p "$root/android" "$@"
