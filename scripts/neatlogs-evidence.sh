#!/usr/bin/env bash
# Produce the neatlogs evidence for the submission in one run.
#
#   read -rs NEATLOGS_API_KEY && export NEATLOGS_API_KEY   # paste the project key; not echoed, not saved
#   ./scripts/neatlogs-evidence.sh
#
# It sends two traces from the agent as it was before the remediation order was fixed, then one
# from each playbook as it is now, and prints the delivery counters so you can see they arrived.
# The "before" runs come from a git worktree at 0817443, so your working tree is never touched.
#
# Without a key it still runs everything and prints the measured numbers; only the export is off.
set -euo pipefail
cd "$(dirname "$0")/.."
root=$(pwd)
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && . ./.env && set +a

PY=python3
[[ -x "$root/.venv/bin/python" ]] && PY="$root/.venv/bin/python"
BEFORE_COMMIT="${BEFORE_COMMIT:-0817443}"
WORK="${TMPDIR:-/tmp}/rook-before-$$"

note() { printf '\n==> %s\n' "$*"; }

if [[ -z "${NEATLOGS_API_KEY:-}" ]]; then
  cat >&2 <<'MSG'
NEATLOGS_API_KEY is not set, so nothing will be exported to the dashboard.
  read -rs NEATLOGS_API_KEY && export NEATLOGS_API_KEY
Continuing anyway, so you can still see the measured numbers.
MSG
fi

note "SDK self-test against the real ingest endpoint"
"$PY" -m neatlogs doctor --probe 2>&1 | tail -15 || echo "   (no doctor command in this SDK build; continuing)"

cleanup() { git worktree remove --force "$WORK" >/dev/null 2>&1 || true; }
trap cleanup EXIT

note "Before: the agent at $BEFORE_COMMIT, which revoked the old key before repairing the services"
git worktree add -f --detach "$WORK" "$BEFORE_COMMIT" >/dev/null
for sc in transient persistent; do
  echo "--- before / $sc"
  (cd "$WORK" && ROOK_DEMO_LABEL=before "$PY" -m rook.demo --scenario "$sc") | tail -22
done

note "After: the agent as it is now, across every playbook"
for sc in signature persistent outage leak referral_clean referral_critical cover_clean cover_unreachable; do
  echo "--- after / $sc"
  ROOK_DEMO_LABEL=after "$PY" -m rook.demo --scenario "$sc" | tail -18
done

note "What to do with this"
cat <<'MSG'
Check that span_export_failures is 0 in the output above.

Open https://app.neatlogs.com, pick the project, and find the workflow "rook-incident-response"
under Traces or Sessions. Filter on the rook.label tag to separate before from after, then paste
the trace URLs into the table at the bottom of evidence/neatlogs-traces.md.

The number to compare between the two labels is dependent_outage_steps: how many steps of the run
left a service that people depend on broken. Before it is 3 on transient and 6 on persistent.
After it is 0 on both.

Worth setting up in the dashboard while you are there:
  - a Detection with the regex sk_test_SYNTH. It must never match; it is a leak tripwire.
  - an Alert on closure.evaluate spans where neatlogs.guardrail.passed = false, which means an
    incident Rook refused to close.
MSG
