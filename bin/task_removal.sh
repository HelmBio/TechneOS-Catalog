#!/usr/bin/env bash
# Thin wrapper around management.scripts.remove_task_run — removal for a human task.
#
# Without a version, this removes the WHOLE task: every task run (and each run's
# MinIO files under task-runs/{slug}/v{N}/{run_id}/...), then every version, then
# the task itself. With a version, it is scoped — that version's runs and the
# version, leaving the task and its other versions in place.
#
# Usage:
#   ./bin/task_removal.sh <task-slug-or-uuid> [version] [options]
#   ./bin/task_removal.sh <slug> --dry-run       # preview the whole removal
#   ./bin/task_removal.sh <slug> v2              # just version 2
#
# Options:
#   --env ENV       Target environment (development, staging, production)
#   --dry-run       Show what would be deleted without making changes
#   --force         Cancel active task runs without prompting
#
# On first run the script prompts for admin login credentials and caches the
# token in ~/.techneos/{env}_token.json for reuse on subsequent runs.
#
# The API URL comes from PLATFORM_API_URL in .env.dev (sourced below), defaulting
# to the local stack.
#
# Examples:
#   ./bin/task_removal.sh <slug>
#   ./bin/task_removal.sh <slug> v2 --dry-run
#   ./bin/task_removal.sh <slug> --force

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1
# Load .env.dev if present (gateway URL); the package index is in pyproject.toml.
# shellcheck disable=SC1091
[ -f "$SCRIPT_DIR/../.env.dev" ] && { set -a; . "$SCRIPT_DIR/../.env.dev"; set +a; }
exec uv run --group tooling python -u -m management.scripts.remove_task_run "$@"
