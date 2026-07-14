#!/usr/bin/env bash
# Thin wrapper around management.scripts.remove_agent.
# Removes an AgentDefinition (by slug or UUID) and cascades to its runs.
#
# Usage:
#   ./bin/agent_removal.sh <slug-or-uuid> [options]
#   ./bin/agent_removal.sh <slug> --dry-run
#   ./bin/agent_removal.sh <slug> --yes
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
# Note: the wheel on the Python package index is NOT removed; only the
# AgentDefinition row in the platform DB. Wheel retention is a separate
# concern handled by the index's policies.
#
# Examples:
#   ./bin/agent_removal.sh <slug>
#   ./bin/agent_removal.sh <slug> --dry-run
#   ./bin/agent_removal.sh <slug> --yes

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1
# Load .env.dev if present (gateway URL); the package index is in pyproject.toml.
# shellcheck disable=SC1091
[ -f "$SCRIPT_DIR/../.env.dev" ] && { set -a; . "$SCRIPT_DIR/../.env.dev"; set +a; }
exec uv run --group tooling python -u -m management.scripts.remove_agent "$@"
