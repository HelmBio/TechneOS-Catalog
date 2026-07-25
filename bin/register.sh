#!/usr/bin/env bash
set -euo pipefail
#
# Register (build + publish + register) ONE catalog entry, from the repo root —
# picks the right uv invocation per entry so you don't have to.
#
# Usage:
#   bin/register.sh <type/slug> [args passed to the script...]
#   bin/register.sh <type> [args passed to each script...]
#   bin/register.sh tools/<slug>
#   bin/register.sh tools/<slug> --activate
#   bin/register.sh datasets/<slug> --upsert
#   bin/register.sh agents/<slug> --env=dev
#   bin/register.sh tools                          # register ALL tools
#
# Options:
#   --env=<dev|prod>   Select the environment config (.env.dev or .env.prod).
#                      Defaults to dev.
#   --help, -h         Show this help message.
#
# Additional flags are passed through to the entry's register script:
#   --skip-build       Skip building the wheel or image.
#   --skip-publish     Build but do not publish to the index.
#   --skip-push        Build but do not push to a remote registry (container tools).
#   --skip-validation  Skip the entry-point check.
#   --activate         Activate the tool version after registration.
#   --upsert           Upsert existing artifact instead of creating new.
#
# <type> is one of: tools, datasets, agents, apps, tasks, pipelines.
# <type/slug> is a catalog entry directory (its build_and_register.py or
# register.py is found automatically); you may also pass the script path directly.
#
# How the invocation is chosen, from `delivery` in the entry's [tool.techneos]:
#   * delivery = "pypi" (pypi tools, agents): the register script imports its own
#     entry point at pre-flight, so it needs that package's deps (e.g. rdkit) —
#     run from the package dir with the `publish` group.
#   * everything else (container tools, and the def-only types: datasets, tasks,
#     pipelines, apps): a container tool validates its entry point statically and
#     builds an image, so its deps live in the image, not on the host. These need
#     only techneos-management — run from the repo root in an ephemeral,
#     lock-free env (`uv run --no-project --with techneos-management`) so the
#     tool resolves against the active env's index instead of a pinned lock.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

show_help() {
  sed -n '3,42p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

# --- Parse flags ---
ENV="dev"
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --help|-h)    show_help ;;
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

entry="${1:-}"
if [ -z "$entry" ]; then
  show_help
fi
shift
entry="${entry%/}"

# --- Resolve entry directories ---
# Valid catalog types
TYPES=("tools" "datasets" "agents" "apps" "tasks" "pipelines")
DIRS=()

if [[ " ${TYPES[*]} " =~ " ${entry} " ]]; then
  # Type-only: loop through all subdirectories
  for d in "$entry"/*/; do
    [ -d "$d" ] || continue
    DIRS+=("${d%/}")
  done
  if [ ${#DIRS[@]} -eq 0 ]; then
    echo "error: no entries found under '$entry'" >&2
    exit 1
  fi
else
  # Single entry (type/slug or script path)
  DIRS=("$entry")
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

# Derive package index URLs from the gateway — the gateway proxies /simple/ to
# the package index and exposes /api/v1/artifacts/wheel for uploads.
GATEWAY="${PLATFORM_API_URL:-http://localhost:8000}"
export UV_DEFAULT_INDEX="${GATEWAY}/simple/"
export UV_EXTRA_INDEX_URL="https://pypi.org/simple/"
export UV_PUBLISH_URL="${GATEWAY}/api/v1/artifacts/wheel"

# Map catalog env names to management library names: dev → local, prod → prod
SCRIPT_ENV="$ENV"
[ "$SCRIPT_ENV" = "dev" ] && SCRIPT_ENV="local"

# techneos-management is env-specific (it lives on the per-env gateway index), so
# the tooling path resolves it ephemerally against UV_DEFAULT_INDEX rather than
# from a committed lock — see the header note. Keep this constraint in sync with
# the root pyproject's `tooling` group.
TOOLING_DEPS=(--with "techneos-management>=0.1,<1" --with "python-dotenv>=1.0")

# --- Register each entry ---
FAILED=0
for entry_dir in "${DIRS[@]}"; do
  # Resolve the entry directory + its register script.
  case "$entry_dir" in
    */build_and_register.py|*/register.py)
      script="$entry_dir"; dir="$(dirname "$entry_dir")" ;;
    *)
      dir="$entry_dir"
      if   [ -f "$dir/build_and_register.py" ]; then script="$dir/build_and_register.py"
      elif [ -f "$dir/register.py" ];           then script="$dir/register.py"
      else echo "error: no build_and_register.py or register.py under '$dir'" >&2; FAILED=1; continue
      fi ;;
  esac

  delivery=""
  if [ -f "$dir/pyproject.toml" ]; then
    delivery="$(sed -n 's/^delivery[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$dir/pyproject.toml" | head -1)"
  fi

  if [ "$delivery" = "pypi" ]; then
    echo "=== $script (pypi: package dir + publish group) ==="
    ( cd "$dir" && uv run --group publish python "$(basename "$script")" --env="$SCRIPT_ENV" "$@" )
  else
    echo "=== $script (root: ephemeral tooling env) ==="
    uv run --no-project --python 3.12 "${TOOLING_DEPS[@]}" \
      python "$script" --env="$SCRIPT_ENV" "$@"
  fi
done

exit $FAILED
