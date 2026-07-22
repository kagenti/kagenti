#!/usr/bin/env bash
# Regression test for https://github.com/rossoctl/rossoctl/issues/1822
#
# `_adopt_for_helm` in setup-rossoctl.sh builds an optional `-n <ns>` flag as a
# bash array. When the helper is called for cluster-scoped resources (no
# namespace), that array stays empty. Under `set -u` (nounset), Bash < 4.4 —
# notably macOS's system Bash 3.2 — aborts with
#
#     setup-rossoctl.sh: line NNN: ns_flag[@]: unbound variable
#
# when expanding "${ns_flag[@]}". The OpenShift installer enables `set -u`
# (`set -euo pipefail`), so the install dies right after creating the
# istio-mesh-root-ca certificate.
#
# This test extracts the *real* function from setup-rossoctl.sh and exercises
# both the cluster-scoped (empty namespace) and namespaced paths under
# `set -u`. Reproduce the original failure under old Bash:
#
#     docker run --rm -v "$PWD:/work" -w /work bash:3.2 \
#       scripts/ocp/tests/test_adopt_for_helm.sh
#
# and guard against regressions under modern Bash:
#
#     bash scripts/ocp/tests/test_adopt_for_helm.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../setup-rossoctl.sh"

# Extract just the _adopt_for_helm function definition (no need to run the
# whole installer, which executes top-level install steps on source).
fn="$(sed -n '/^_adopt_for_helm() {/,/^}/p' "$TARGET")"
if [ -z "$fn" ]; then
  echo "FAIL: could not extract _adopt_for_helm from $TARGET"
  exit 2
fi
eval "$fn"

# Stub kubectl: succeed on every call so all three expansion sites
# (get / label / annotate) inside the function are exercised.
_stub_kubectl() { return 0; }
KUBECTL=_stub_kubectl

err_file="$(mktemp)"
trap 'rm -f "$err_file"' EXIT
failures=0

run_case() {
  local desc="$1"; shift
  if ( set -u; _adopt_for_helm "$@" ) 2>"$err_file"; then
    echo "PASS: $desc"
  else
    echo "FAIL: $desc errored:"
    sed 's/^/    /' "$err_file"
    failures=$((failures + 1))
  fi
}

# Case 1: cluster-scoped resource, no namespace — the issue-1822 trigger.
run_case "cluster-scoped call (empty namespace)" clusterissuer istio-mesh-root-selfsigned

# Case 2: namespaced resource — must keep working too.
run_case "namespaced call" certificate istio-mesh-root-ca cert-manager

if [ "$failures" -eq 0 ]; then
  echo "OK: all _adopt_for_helm cases passed"
  exit 0
fi
echo "FAILED: $failures case(s)"
exit 1
