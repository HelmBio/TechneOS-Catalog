#!/usr/bin/env bash
# Thin wrapper around management.scripts.remove_app.
# Removes an App (by slug or UUID) and stops its embedded container.
#
# Usage:
#   ./bin/app_removal.sh <slug-or-uuid> [options]
#   ./bin/app_removal.sh <slug> --dry-run
#   ./bin/app_removal.sh <slug> --yes
#
# Options:
#   --env ENV       Target environment (development, staging, production)
#   --dry-run       Show what would be deleted without making changes
#   --yes, -y       Skip the interactive confirmation prompt
#
# On first run the script prompts for admin login credentials and caches the
# token in ~/.techneos/{env}_token.json for reuse on subsequent runs.
#
# The API URL comes from PLATFORM_API_URL in .env.dev (sourced below), defaulting
# to the local stack.
#
# Examples:
#   ./bin/app_removal.sh <slug>
#   ./bin/app_removal.sh <slug> --dry-run
#   ./bin/app_removal.sh <slug> --yes

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1
# Load .env.dev if present (gateway URL); the package index is in pyproject.toml.
# shellcheck disable=SC1091
[ -f "$SCRIPT_DIR/../.env.dev" ] && { set -a; . "$SCRIPT_DIR/../.env.dev"; set +a; }
exec uv run --group tooling python -u -m management.scripts.remove_app "$@"
