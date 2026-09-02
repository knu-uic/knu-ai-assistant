#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
api_dir="$(cd "$script_dir/../.." && pwd)"
python_bin="${PYTHON_BIN:-$api_dir/../../.venv/bin/python}"
java_home_bin="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21}"
javac_bin="$java_home_bin/bin/javac"
jar_bin="$java_home_bin/bin/jar"

if [[ ! -x "$javac_bin" || ! -x "$jar_bin" ]]; then
  echo "JDK 21을 찾지 못했습니다. JAVA_HOME을 지정하세요." >&2
  exit 1
fi

build_tmp="$(mktemp -d /tmp/codmes-hwp2hwpx.XXXXXX)"
trap 'rm -rf "$build_tmp"' EXIT
mkdir -p "$script_dir/build" "$build_tmp/classes"

"$python_bin" -m pip install --quiet --target "$build_tmp/package" hwp2hwpx==1.0.1
git init "$build_tmp/source"
git -C "$build_tmp/source" remote add origin https://github.com/neolord0/hwp2hwpx.git
git -C "$build_tmp/source" fetch --depth 1 origin edc05278506b663d5bdd98050a51f54b7ff5e0bc
git -C "$build_tmp/source" checkout --detach FETCH_HEAD
source_revision="$(git -C "$build_tmp/source" rev-parse HEAD)"
if [[ "$source_revision" != "edc05278506b663d5bdd98050a51f54b7ff5e0bc" ]]; then
  echo "검증되지 않은 hwp2hwpx revision: $source_revision" >&2
  exit 1
fi
cp "$build_tmp/source/src/main/java/kr/dogfoot/hwp2hwpx/ForContentHPFFile.java" \
  "$build_tmp/ForContentHPFFile.java"
patch "$build_tmp/ForContentHPFFile.java" < "$script_dir/null-extension.patch"

source_jar="$build_tmp/package/hwp2hwpx/jars/hwp2hwpx.jar"
output_jar="$script_dir/build/hwp2hwpx-patched.jar"
"$javac_bin" -encoding UTF-8 -cp "$source_jar" \
  -d "$build_tmp/classes" "$build_tmp/ForContentHPFFile.java"
cp "$source_jar" "$output_jar"
"$jar_bin" uf "$output_jar" \
  -C "$build_tmp/classes" kr/dogfoot/hwp2hwpx/ForContentHPFFile.class
echo "$output_jar"
