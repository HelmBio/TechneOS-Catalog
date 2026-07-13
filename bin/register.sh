#!/usr/bin/env bash
set -euo pipefail
#
# Register (build + publish + register) ONE catalog entry, from the repo root —
# picks the right uv invocation per entry so you don't have to.
#
# Usage:
#   bin/register.sh <type/slug> [args passed to the script...]
#   bin/register.sh tools/<slug>
#   bin/register.sh tools/<slug> --activate
#   bin/register.sh datasets/<slug> --upsert
#   bin/register.sh agents/<slug> --env=local
#
# <type/slug> is a catalog entry directory (its build_and_register.py or
# register.py is found automatically); you may also pass the script path directly.
#
# How the invocation is chosen:
#   * PYPI tools import their entry point at pre-flight, so they need the package's
#     own deps (e.g. rdkit) — run from the package dir with the `publish` group.
#   * Everything else (container tools, agents, apps, datasets, tasks, pipelines)
#     only needs techneos-management — run from the repo root with the `tooling` group.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

entry="${1:-}"
if [ -z "$entry" ]; then
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'   # print the usage header
  exit 1
fi
shift
entry="${entry%/}"

# Resolve the entry directory + its register script.
case "$entry" in
  */build_and_register.py|*/register.py)
    script="$entry"; dir="$(dirname "$entry")" ;;
  *)
    dir="$entry"
    if   [ -f "$dir/build_and_register.py" ]; then script="$dir/build_and_register.py"
    elif [ -f "$dir/register.py" ];           then script="$dir/register.py"
    else echo "error: no build_and_register.py or register.py under '$dir'" >&2; exit 1
    fi ;;
esac

# Load .env.dev if present, for a non-default gateway URL (PLATFORM_API_URL). The
# package index is declared in pyproject.toml, so uv needs no extra setup.
# shellcheck disable=SC1091
[ -f "$REPO_ROOT/.env.dev" ] && { set -a; . "$REPO_ROOT/.env.dev"; set +a; }

if grep -q "import_module" "$script"; then
  echo "=== $script (pypi: package dir + publish group) ==="
  ( cd "$dir" && exec uv run --group publish python "$(basename "$script")" "$@" )
else
  echo "=== $script (root + tooling group) ==="
  exec uv run --group tooling python "$script" "$@"
fi
