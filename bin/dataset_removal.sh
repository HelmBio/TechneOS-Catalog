#!/usr/bin/env bash
# Thin wrapper around management.scripts.remove_dataset.
# Removes a dataset (all versions) or a single dataset version.
# Also cancels referencing pipeline runs and deletes files from MinIO.
#
# Usage:
#   ./bin/dataset_removal.sh <slug-or-uuid> [version] [options]
#   ./bin/dataset_removal.sh <slug> v2 --dry-run
#
# Options:
#   --env=<dev|prod> Select the environment config (.env.dev or .env.prod).
#                    Defaults to dev.
#   --dry-run        Show what would be deleted without making changes
#   --force          Cancel active dependent runs automatically
#
# On first run the script prompts for admin login credentials and caches the
# token in ~/.techneos/{env}_token.json for reuse on subsequent runs.
#
# Examples:
#   ./bin/dataset_removal.sh <slug>
#   ./bin/dataset_removal.sh <slug> v4 --dry-run
#   ./bin/dataset_removal.sh <slug> v4 --force
#   ./bin/dataset_removal.sh <slug> --env=prod --dry-run

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1

# --- Parse --env flag (dev|prod, default: dev) ---
ENV="dev"
ARGS=()
for arg in "$@"; do
  case "$arg" in
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

# Load environment config (.env.dev or .env.prod).
ENV_FILE="$SCRIPT_DIR/../.env.${ENV}"
if [ -f "$ENV_FILE" ]; then
  echo "=== Loading $ENV_FILE ==="
  # shellcheck disable=SC1090
  { set -a; . "$ENV_FILE"; set +a; }
else
  echo "warning: $ENV_FILE not found, using defaults" >&2
fi

exec uv run --group tooling python -u -m management.scripts.remove_dataset "$@"
