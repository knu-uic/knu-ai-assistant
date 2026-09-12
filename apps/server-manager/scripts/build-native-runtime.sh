#!/usr/bin/env bash
set -euo pipefail

# Build relocatable, loopback-only PostgreSQL/pgvector and Redis distributions.
# Homebrew/system prefixes are intentionally never copied into a release.

postgres_version="${KNU_POSTGRES_VERSION:-16.15}"
postgres_sha256="${KNU_POSTGRES_SHA256:-c1575341fa7bd40f5274ea465b34390f4dc64cdd0770af327005caaeb9f6b7ed}"
pgvector_version="${KNU_PGVECTOR_VERSION:-0.8.6}"
pgvector_commit="${KNU_PGVECTOR_COMMIT:-8ee86c96f0fd72390f890aa8a336fda6d3ab4c6c}"
redis_version="${KNU_REDIS_VERSION:-7.2.15}"
redis_sha256="${KNU_REDIS_SHA256:-7bf7975331511fdb788e85dae63964b128fccee1df026a10db57444babc9c9c4}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
manager_root="$(cd "$script_dir/.." && pwd)"
platform="$(uname -s | tr '[:upper:]' '[:lower:]')"
architecture="$(uname -m)"
output_root="${1:-$manager_root/native-runtime/$platform-$architecture}"

case "$platform" in
  darwin|linux) ;;
  *) echo "This source builder currently supports macOS and Linux; got $platform" >&2; exit 1 ;;
esac

if [ -e "$output_root" ]; then
  echo "Output already exists; choose a new empty path: $output_root" >&2
  exit 1
fi

build_root="$(mktemp -d "${TMPDIR:-/tmp}/knu-runtime.XXXXXX")"
cleanup() { rm -rf "$build_root"; }
trap cleanup EXIT
mkdir -p "$output_root/postgres" "$output_root/redis/bin" "$output_root/licenses"

jobs="${KNU_BUILD_JOBS:-}"
if [ -z "$jobs" ]; then
  jobs="$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
fi

verify_sha256() {
  local expected="$1" file="$2" actual
  if command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  else
    actual="$(sha256sum "$file" | awk '{print $1}')"
  fi
  if [ "$actual" != "$expected" ]; then
    echo "SHA-256 mismatch for $file" >&2
    exit 1
  fi
}

postgres_archive="$build_root/postgresql.tar.bz2"
curl --fail --location --silent --show-error \
  "https://ftp.postgresql.org/pub/source/v$postgres_version/postgresql-$postgres_version.tar.bz2" \
  --output "$postgres_archive"
verify_sha256 "$postgres_sha256" "$postgres_archive"
tar -xjf "$postgres_archive" -C "$build_root"
pushd "$build_root/postgresql-$postgres_version" >/dev/null
./configure \
  --prefix="$output_root/postgres" \
  --disable-nls \
  --without-icu \
  --without-readline \
  --without-zlib
make -j"$jobs"
make install
make -C contrib/pg_trgm -j"$jobs"
make -C contrib/pg_trgm install
cp COPYRIGHT "$output_root/licenses/PostgreSQL.txt"
popd >/dev/null

git clone --quiet https://github.com/pgvector/pgvector.git "$build_root/pgvector"
pushd "$build_root/pgvector" >/dev/null
git checkout --quiet "$pgvector_commit"
if [ "$(git describe --tags --exact-match)" != "v$pgvector_version" ]; then
  echo "pgvector commit does not match v$pgvector_version" >&2
  exit 1
fi
make OPTFLAGS="" PG_CONFIG="$output_root/postgres/bin/pg_config" -j"$jobs"
make OPTFLAGS="" PG_CONFIG="$output_root/postgres/bin/pg_config" install
cp LICENSE "$output_root/licenses/pgvector.txt"
popd >/dev/null

redis_archive="$build_root/redis.tar.gz"
curl --fail --location --silent --show-error \
  "https://download.redis.io/releases/redis-$redis_version.tar.gz" \
  --output "$redis_archive"
verify_sha256 "$redis_sha256" "$redis_archive"
tar -xzf "$redis_archive" -C "$build_root"
pushd "$build_root/redis-$redis_version" >/dev/null
make -j"$jobs" BUILD_TLS=no MALLOC=libc redis-server
cp src/redis-server "$output_root/redis/bin/redis-server"
chmod 755 "$output_root/redis/bin/redis-server"
cp COPYING "$output_root/licenses/Redis.txt"
popd >/dev/null

java_home="${KNU_BUILD_JAVA_HOME:-${JAVA_HOME:-}}"
if [ -z "$java_home" ] && [ "$platform" = "darwin" ]; then
  java_home="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
fi
if [ -z "$java_home" ] || [ ! -x "$java_home/bin/jlink" ]; then
  echo "JDK 21 with jlink is required. Set KNU_BUILD_JAVA_HOME." >&2
  exit 1
fi
"$java_home/bin/jlink" \
  --module-path "$java_home/jmods" \
  --add-modules ALL-MODULE-PATH \
  --strip-debug \
  --no-header-files \
  --no-man-pages \
  --output "$output_root/java"

"$output_root/postgres/bin/postgres" --version
"$output_root/redis/bin/redis-server" --version
"$output_root/java/bin/java" -version
test -f "$output_root/postgres/share/extension/vector.control" \
  || test -f "$output_root/postgres/share/postgresql/extension/vector.control"
test -f "$output_root/postgres/share/extension/pg_trgm.control" \
  || test -f "$output_root/postgres/share/postgresql/extension/pg_trgm.control"

echo "Native runtime ready: $output_root"
echo "KNU_POSTGRES_RUNTIME=$output_root/postgres"
echo "KNU_REDIS_RUNTIME=$output_root/redis"
echo "KNU_JAVA_RUNTIME=$output_root/java"
