#!/usr/bin/env bash
# Thin wrapper around management.scripts.remove_tool.
# Removes a tool (all versions) or a single tool version.
# Also cancels referencing pipeline runs.
#
# Usage:
#   ./bin/tool_removal.sh <slug-or-uuid> [version] [options]
#   ./bin/tool_removal.sh <slug> v3 --dry-run
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
#   ./bin/tool_removal.sh <slug>
#   ./bin/tool_removal.sh <slug> v3 --dry-run
#   ./bin/tool_removal.sh <slug> v3 --force

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1
# Load .env.dev if present (gateway URL); the package index is in pyproject.toml.
# shellcheck disable=SC1091
[ -f "$SCRIPT_DIR/../.env.dev" ] && { set -a; . "$SCRIPT_DIR/../.env.dev"; set +a; }
exec uv run --group tooling python -u -m management.scripts.remove_tool "$@"
