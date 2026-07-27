#!/usr/bin/env bash
# Run every suite and report a combined result.
#
# No arguments, no Home Assistant installation, no router. Each suite resolves
# the package from the repository it lives in.
set -u

cd "$(dirname "$0")" || exit 1

PYTHON="${PYTHON:-python3}"
failed=0

for suite in test_*.py; do
    printf '%-20s' "${suite%.py}"

    if output=$("$PYTHON" "$suite" 2>&1); then
        printf 'PASS\n'
    else
        printf 'FAIL\n'
        printf '%s\n' "$output" | sed 's/^/    /'
        failed=$((failed + 1))
    fi
done

echo

if [ "$failed" -eq 0 ]; then
    echo "All suites passed"
    exit 0
fi

echo "$failed suite(s) failed"
exit 1
