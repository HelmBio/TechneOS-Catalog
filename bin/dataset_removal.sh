#!/usr/bin/env bash
# Thin wrapper around management.scripts.remove_dataset.
# Removes a dataset (all versions) or a single dataset version.
# Also cancels referencing pipeline runs and deletes files from MinIO.
#
# Usage:
#   ./bin/dataset_removal.sh <slug-or-uuid> [version] [options]
#   ./bin/dataset_removal.sh --env local <slug> v2 --dry-run
#
# Options:
#   --env ENV       Target environment (development, staging, production)
#   --dry-run       Show what would be deleted without making changes
#   --force         Cancel active dependent runs automatically
#
# On first run the script prompts for admin login credentials and caches the
# token in ~/.techneos/{env}_token.json for reuse on subsequent runs.
#
# The API URL comes from PLATFORM_API_URL in .env.dev (sourced below), defaulting
# to the local stack.
#
# Examples:
#   ./bin/dataset_removal.sh <slug>
#   ./bin/dataset_removal.sh <slug> v4 --dry-run
#   ./bin/dataset_removal.sh <slug> v4 --force
#   ./bin/dataset_removal.sh --env local <slug> v2 --dry-run

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1
# Load .env.dev if present (gateway URL); the package index is in pyproject.toml.
# shellcheck disable=SC1091
[ -f "$SCRIPT_DIR/../.env.dev" ] && { set -a; . "$SCRIPT_DIR/../.env.dev"; set +a; }
exec uv run --group tooling python -u -m management.scripts.remove_dataset "$@"
