#!/usr/bin/env bash
set -euo pipefail
# Run with the existing WSL Android toolchain; no APK, network, emulator, or production data.
root="$(cd "$(dirname "$0")/.." && pwd)"
cache="${GRADLE_USER_HOME:-$HOME/.gradle}/caches/modules-2/files-2.1"
jar() { find "$cache/$1" -name '*.jar' -print -quit 2>/dev/null; }
compiler="$(jar org.jetbrains.kotlin/kotlin-compiler-embeddable/2.1.20)"
stdlib="$(jar org.jetbrains.kotlin/kotlin-stdlib/2.1.20)"
json="$(jar org.json/json)"
annotations="$(jar org.jetbrains/annotations)"
compiler_cp="$compiler:$stdlib:$(jar org.jetbrains.kotlin/kotlin-reflect):$(jar org.jetbrains.intellij.deps/trove4j):$(jar org.jetbrains.kotlinx/kotlinx-coroutines-core-jvm):$annotations"
[[ -n "$compiler" && -n "$stdlib" && -n "$json" ]] || { echo 'Use the configured WSL Android build environment first.' >&2; exit 1; }
output="$(mktemp -d /tmp/trotter-native-share-tests.XXXXXX)"
java -cp "$compiler_cp" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -no-stdlib -no-reflect -classpath "$stdlib:$json:$annotations" -d "$output/tests.jar" \
  "$root/android/app/src/main/java/com/trotter/mobilev2/DreamShareInbox.kt" \
  "$root/android/app/src/main/java/com/trotter/mobilev2/DreamShareReceiptPolicy.kt" \
  "$root/scripts/native-share-tests/DreamShareInboxTest.kt" \
  "$root/scripts/native-share-tests/DreamShareReceiptPolicyTest.kt"
java -cp "$output/tests.jar:$stdlib:$json" com.trotter.mobilev2.DreamShareInboxTestKt
java -cp "$output/tests.jar:$stdlib:$json" com.trotter.mobilev2.DreamShareReceiptPolicyTestKt
