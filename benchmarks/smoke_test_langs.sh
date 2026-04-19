#!/usr/bin/env bash
# Smoke test each non-Python language in the Aider Polyglot benchmark.
# Copies one exercise to a temp dir, overwrites the stub with the reference
# solution (.meta/example.*), and runs the native test runner.
# A green run confirms the toolchain + benchmark layout is sane BEFORE we
# let the agent loose on 225 exercises.
#
# Fixes discovered during first run:
#   - cpp: CMakeLists derives source name from dir name — must copy to a
#     dir literally named after the exercise.
#   - rust: Exercism marks advanced tests #[ignore] — must run with
#     `cargo test -- --include-ignored` to count them all.
#   - js: Exercism marks advanced tests xit/xtest — must strip to it/test
#     before running or jest silently skips them.
#   - java: gradle --offline fails on empty cache — drop for first run.
#
# Exits non-zero on any language failure.
set -u
export PATH="$HOME/.cargo/bin:$PATH"

BENCH="$HOME/Documents/polyglot-benchmark"
FAIL=0

run_smoke() {
    local lang="$1" ex="$2" desc="$3"
    local src="$BENCH/$lang/exercises/practice/$ex"
    local work="/tmp/smoke_${lang}_$$/$ex"
    rm -rf "/tmp/smoke_${lang}_$$"
    mkdir -p "$work"

    echo
    echo "=============================================="
    echo "  [$lang] $ex  — $desc"
    echo "=============================================="

    if [ ! -d "$src" ]; then
        echo "  FAIL: source dir not found: $src"
        FAIL=$((FAIL + 1))
        return 1
    fi

    # Copy exercise into a dir literally named after the exercise
    # (required for cpp CMakeLists; harmless for others).
    cp -r "$src"/. "$work/"
    cd "$work" || return 1

    local rc=1
    case "$lang" in
    go)
        local stub
        stub=$(find "$work" -maxdepth 1 -name '*.go' ! -name '*_test.go' ! -name 'go.mod' | head -1)
        cp "$src/.meta/example.go" "$stub"
        go test ./... 2>&1 | tail -20
        rc=${PIPESTATUS[0]}
        ;;
    cpp)
        local cpp_stub h_stub
        cpp_stub=$(find "$work" -maxdepth 1 -name '*.cpp' ! -name '*_test.cpp' | head -1)
        h_stub=$(find "$work" -maxdepth 1 -name '*.h' | head -1)
        [ -n "$cpp_stub" ] && cp "$src/.meta/example.cpp" "$cpp_stub"
        [ -n "$h_stub" ]   && cp "$src/.meta/example.h"   "$h_stub"
        # No EXERCISM_TEST_SUITE → uses vendored test/catch.hpp (Catch2 v2).
        # EXERCISM_RUN_ALL_TESTS enables test cases guarded by #ifdef.
        # cmake --build also runs the custom test_<name> target, so its
        # exit code is authoritative — ctest is not wired up by this layout.
        cmake -S . -B build -DCMAKE_CXX_FLAGS="-DEXERCISM_RUN_ALL_TESTS" 2>&1 | tail -3
        cmake --build build 2>&1 | tail -8
        rc=${PIPESTATUS[0]}
        ;;
    rust)
        cp "$src/.meta/example.rs" "$work/src/lib.rs"
        cargo test -- --include-ignored 2>&1 | tail -20
        rc=${PIPESTATUS[0]}
        ;;
    javascript)
        local stub spec
        stub=$(find "$work" -maxdepth 1 -name '*.js' ! -name '*.spec.js' ! -name 'babel.config.js' | head -1)
        spec=$(find "$work" -maxdepth 1 -name '*.spec.js' | head -1)
        cp "$src/.meta/proof.ci.js" "$stub"
        # Strip Exercism skip markers so ALL tests actually run
        sed -i -E 's/\bxit\(/it(/g; s/\bxtest\(/test(/g; s/\bxdescribe\(/describe(/g' "$spec"
        npm install --silent 2>&1 | tail -3
        npm test 2>&1 | tail -20
        rc=${PIPESTATUS[0]}
        ;;
    java)
        local ref tgt
        ref=$(find "$src/.meta/src/reference/java" -name '*.java' | head -1)
        tgt=$(find "$work/src/main/java" -name '*.java' | head -1)
        cp "$ref" "$tgt"
        # Strip JUnit5 @Disabled annotations from every test file so all
        # test methods actually run. Exercism's java exercises gate advanced
        # tests behind @Disabled("Remove to run test").
        find "$work/src/test/java" -name '*.java' -print0 | while IFS= read -r -d '' f; do
            sed -i -E '/^[[:space:]]*@Disabled\b/d' "$f"
        done
        chmod +x "$work/gradlew" 2>/dev/null || true
        "$work/gradlew" test --no-daemon 2>&1 | tail -25
        rc=${PIPESTATUS[0]}
        ;;
    esac

    cd - > /dev/null || true
    if [ "$rc" = "0" ]; then
        echo "  ✓ $lang smoke OK"
    else
        echo "  ✗ $lang smoke FAILED (rc=$rc)"
        FAIL=$((FAIL + 1))
    fi
    rm -rf "/tmp/smoke_${lang}_$$"
}

run_smoke go         beer-song      "string pattern generation"
run_smoke cpp        allergies      "bitmask lookup"
run_smoke rust       acronym        "split + first-char"
run_smoke javascript beer-song      "string pattern generation"
run_smoke java       all-your-base  "base conversion"

echo
echo "=============================================="
if [ "$FAIL" = "0" ]; then
    echo "  ALL SMOKE TESTS PASSED"
    exit 0
else
    echo "  $FAIL LANGUAGE(S) FAILED SMOKE TEST"
    exit 1
fi
