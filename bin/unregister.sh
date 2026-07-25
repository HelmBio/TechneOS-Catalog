#!/usr/bin/env bash
set -euo pipefail
#
# Unregister (remove) ONE catalog resource from the platform, from the repo root.
# One entry point for every resource type — the removal counterpart to
# register.sh, replacing the per-type bin/<type>_removal.sh wrappers.
#
# Usage:
#   bin/unregister.sh <type> <slug-or-uuid> [version] [options]
#   bin/unregister.sh tool <slug>
#   bin/unregister.sh tool <slug> v3 --dry-run
#   bin/unregister.sh dataset <slug> v2 --force
#   bin/unregister.sh agent <slug> --yes
#   bin/unregister.sh pipeline <slug> --env=prod --dry-run
#
# <type> is one of: tool, agent, app, dataset, task, pipeline
#   (plural forms — tools, agents, … — are accepted too).
#
# Options:
#   --env=<dev|prod>   Select the environment config (.env.dev or .env.prod) and
#                      the token cache (~/.techneos/<env>_token.json). Default: dev.
#   --help, -h         Show this help message.
#
# Flags after the slug are passed through to the removal script:
#   --dry-run          Show what would be deleted without making changes.
#   --force            Cancel active dependent runs automatically.
#   --yes, -y          Skip the interactive confirmation prompt (agents, apps).
#
# What each type removes (delegates to management.scripts.remove_<type>):
#   tool       a tool (all versions) or one version; cancels referencing runs
#   agent      an AgentDefinition and cascades to its runs
#   app        an App and stops its embedded container
#   dataset    a dataset (all/one version); cancels runs; deletes MinIO files
#   task       a human task (all/one version) and its task-run files
#   pipeline   a pipeline definition (all/one version) and its runs
#
# On first run you are prompted for admin login; the token is cached in
# ~/.techneos/<env>_token.json for reuse. techneos-management is resolved
# ephemerally against the per-env gateway index (like register.sh), so no lock
# pins it to a single environment.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

show_help() {
  sed -n '3,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

# --- Parse flags (--env / --help); keep the rest for the subcommand ---
ENV="dev"
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --help|-h) show_help ;;
    --env=*)
      ENV="${arg#--env=}"
      if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
        echo "error: --env must be 'dev' or 'prod', got '$ENV'" >&2
        exit 1
      fi
      ;;
    *)
      ARGS+=("$arg")
      ;;
  esac
done
set -- "${ARGS[@]}"

# --- Resolve the resource type (subcommand) → management removal module ---
type_arg="${1:-}"
if [ -z "$type_arg" ]; then
  show_help
fi
shift

case "$type_arg" in
  tool|tools)         module="remove_tool" ;;
  agent|agents)       module="remove_agent" ;;
  app|apps)           module="remove_app" ;;
  dataset|datasets)   module="remove_dataset" ;;
  task|tasks)         module="remove_task_run" ;;
  pipeline|pipelines) module="remove_pipeline" ;;
  *)
    echo "error: unknown resource type '$type_arg'" >&2
    echo "       valid types: tool, agent, app, dataset, task, pipeline" >&2
    exit 1
    ;;
esac

ref="${1:-}"
if [ -z "$ref" ]; then
  echo "error: missing <slug-or-uuid> for '$type_arg'" >&2
  echo "       usage: bin/unregister.sh $type_arg <slug-or-uuid> [version] [options]" >&2
  exit 1
fi

# Load environment config (.env.dev or .env.prod).
ENV_FILE="$REPO_ROOT/.env.${ENV}"
if [ -f "$ENV_FILE" ]; then
  echo "=== Loading $ENV_FILE ==="
  # shellcheck disable=SC1090
  { set -a; . "$ENV_FILE"; set +a; }
else
  echo "warning: $ENV_FILE not found, using defaults" >&2
fi

# Derive the package index from the gateway so the ephemeral tooling env resolves
# techneos-management against the active env's index — same as register.sh, so no
# committed lock pins it to one environment.
GATEWAY="${PLATFORM_API_URL:-http://localhost:8000}"
export UV_DEFAULT_INDEX="${GATEWAY}/simple/"
export UV_EXTRA_INDEX_URL="https://pypi.org/simple/"

# Map catalog env names to management library names: dev → local, prod → prod.
# The module canonicalises this to the token-cache name (local → development).
SCRIPT_ENV="$ENV"
[ "$SCRIPT_ENV" = "dev" ] && SCRIPT_ENV="local"

# techneos-management is env-specific (it lives on the per-env gateway index), so
# resolve it ephemerally against UV_DEFAULT_INDEX rather than from a committed
# lock — see register.sh's header note.
TOOLING_DEPS=(--with "techneos-management>=0.1,<1" --with "python-dotenv>=1.0")

echo "=== unregister $type_arg: $ref (env: $SCRIPT_ENV) ==="
exec uv run --no-project --python 3.12 "${TOOLING_DEPS[@]}" \
  python -u -m "management.scripts.${module}" --env="$SCRIPT_ENV" "$@"
