#!/usr/bin/env bash
# One-command production audit: login, grader key, promptfoo run, optional UI.
# See evals/README.md ("Production audits").
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: evals/run-audit.sh [--view] [--help]

Runs the promptfoo eval suite against the eval endpoint (ADMIN_TECHNICAL only).
You are prompted for an admin user and a silent password.

Options:
  --view    After the run, open the promptfoo UI bound to 127.0.0.1 only and
            print the ssh tunnel command to reach it.
  --help    Show this help.

Environment (all optional):
  INTERNAL_EVAL_BASE_URL   default https://agent.qeva-ai.com
  EVAL_GRADER_BASE_URL     default https://openrouter.ai/api/v1
  EVAL_GRADER_MODEL        default anthropic/claude-haiku-4.5
  EVAL_GRADER_API_KEY      default: read from the running backend container's
                           /run/secrets/backend.env (LLM_API_KEY, then
                           OPENROUTER_API_KEY); never printed
  EVAL_RESULTS_DIR         default $HOME/.cache/agente-ai-evals
  EVAL_VIEW_PORT           default 15500

Exit code is promptfoo's (100 means some tests failed).
USAGE
}

VIEW=0
for arg in "$@"; do
  case "$arg" in
    --view) VIEW=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

EVALS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${INTERNAL_EVAL_BASE_URL:-https://agent.qeva-ai.com}"
RESULTS_DIR="${EVAL_RESULTS_DIR:-$HOME/.cache/agente-ai-evals}"
VIEW_PORT="${EVAL_VIEW_PORT:-15500}"

for tool in python3 curl npx; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Missing required tool: $tool" >&2
    exit 1
  }
done

COOKIE_JAR="$(mktemp)"
chmod 600 "$COOKIE_JAR"
cleanup() { rm -f "$COOKIE_JAR"; }
trap cleanup EXIT

# --- Grader key (never echoed) ---------------------------------------------
read_backend_secret() {
  local container
  container="$(docker ps --format '{{.Names}}' 2>/dev/null | grep 'agente-clinica_backend' | head -n 1 || true)"
  [ -n "$container" ] || return 1
  docker exec "$container" sh -c '
    f=/run/secrets/backend.env
    [ -r "$f" ] || exit 1
    for k in LLM_API_KEY OPENROUTER_API_KEY; do
      v="$(grep -E "^${k}=" "$f" | head -n 1 | cut -d= -f2-)"
      if [ -n "$v" ]; then printf "%s" "$v" | tr -d "\"'"'"'"; exit 0; fi
    done
    exit 1
  ' 2>/dev/null
}

if [ -z "${EVAL_GRADER_API_KEY:-}" ]; then
  EVAL_GRADER_API_KEY="$(read_backend_secret || true)"
fi
if [ -z "${EVAL_GRADER_API_KEY:-}" ]; then
  echo "Grader key not found: set EVAL_GRADER_API_KEY, or run this on the host of the" >&2
  echo "backend container (agente-clinica_backend) so it can be read from its secret." >&2
  exit 1
fi
export EVAL_GRADER_API_KEY
export EVAL_GRADER_BASE_URL="${EVAL_GRADER_BASE_URL:-https://openrouter.ai/api/v1}"
export EVAL_GRADER_MODEL="${EVAL_GRADER_MODEL:-anthropic/claude-haiku-4.5}"

# --- Login (password only via a silent prompt and stdin) -------------------
read -r -p 'Admin user: ' ADMIN_USER
read -r -s -p 'Admin password: ' ADMIN_PASSWORD
echo
LOGIN_RESPONSE="$(
  ADMIN_USER="$ADMIN_USER" ADMIN_PASSWORD="$ADMIN_PASSWORD" python3 -c '
import json, os
print(json.dumps({"username": os.environ["ADMIN_USER"], "password": os.environ["ADMIN_PASSWORD"]}))
' | curl -sS -c "$COOKIE_JAR" -H 'Content-Type: application/json' \
    --data @- "$BASE_URL/admin/login"
)"
unset ADMIN_PASSWORD

ROLE="$(printf '%s' "$LOGIN_RESPONSE" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("role", ""))
except Exception:
    print("")
')"
if [ "$ROLE" != "ADMIN_TECHNICAL" ]; then
  echo "Login failed or the account is not ADMIN_TECHNICAL (role: ${ROLE:-none})." >&2
  exit 1
fi

ADMIN_SESSION_COOKIE="$(awk '$6=="admin_session"{print $7}' "$COOKIE_JAR")"
ADMIN_CSRF_COOKIE="$(awk '$6=="admin_csrf"{print $7}' "$COOKIE_JAR")"
if [ -z "$ADMIN_SESSION_COOKIE" ] || [ -z "$ADMIN_CSRF_COOKIE" ]; then
  echo "Login did not return the session cookies." >&2
  exit 1
fi
export ADMIN_SESSION_COOKIE ADMIN_CSRF_COOKIE
rm -f "$COOKIE_JAR"

# --- Run --------------------------------------------------------------------
RUN_ID="audit-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULTS_DIR"
RESULTS_FILE="$RESULTS_DIR/$RUN_ID.json"

export INTERNAL_EVAL_BASE_URL="$BASE_URL"
export EVAL_RUN_ID="$RUN_ID"
export PROMPTFOO_DISABLE_TELEMETRY=1
export PROMPTFOO_DISABLE_SHARING=1

echo "Audit $RUN_ID against $BASE_URL (grader: $EVAL_GRADER_MODEL)"
STATUS=0
npx -y promptfoo@latest eval \
  -c "$EVALS_DIR/promptfooconfig.yaml" \
  --no-cache --no-progress-bar \
  -o "$RESULTS_FILE" || STATUS=$?

echo "Results: $RESULTS_FILE"
if [ -f "$RESULTS_FILE" ]; then
  python3 - "$RESULTS_FILE" <<'PY' || true
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
stats = (data.get("results") or {}).get("stats") or {}
for key in ("successes", "failures", "errors"):
    if key in stats:
        print(f"{key}: {stats[key]}")
PY
fi
echo "promptfoo exit code: $STATUS (100 = some tests failed)"

if [ "$VIEW" -eq 1 ]; then
  echo
  echo "Open the UI from your workstation with:"
  echo "  ssh -N -L $VIEW_PORT:localhost:$VIEW_PORT <user>@<host>"
  echo "then browse http://localhost:$VIEW_PORT (Ctrl+C here to stop)."
  NODE_OPTIONS="--require $EVALS_DIR/localhost-only.cjs" \
    npx -y promptfoo@latest view -n --port "$VIEW_PORT" || true
fi

exit "$STATUS"
