# techneos-catalog — agent / contributor guide

This repo holds the platform's registered content (datasets, tools, pipelines,
apps, agents, tasks). It depends on the platform only through published wheels
(`techneos-tool-runtime`, `techneos-management`) from the package index and the gateway REST API —
there is no source dependency on the platform monorepo. See [README.md](README.md)
for the full layout and how the coupling works; each content type gets an
authoring + registration guide under `docs/guides/`, added alongside that type's
first entry.

## Setup

The repo is pinned to Python 3.12 (`.python-version`). The package index (the
local devpi that serves `techneos-management`) is declared in `pyproject.toml`
(`[[tool.uv.index]]`), so `uv run` / `uv sync` resolve it with no setup — just have
the platform's dev stack up. (Needs `techneos-management >= 0.1`.)

The gateway URL defaults to the local stack; copy the env template —
`cp .env.example .env.dev` — to point at a non-default gateway (`bin/register.sh`
sources it).

## Registering entries

Register an entry against the local gateway (`--env=local`).
The gateway/portal URL comes from `PLATFORM_API_URL` / `PLATFORM_PORTAL_URL` in
`.env.dev` (the wrappers auto-load it). Auth uses the cached `~/.techneos` token or
prompts; pass `--email/--password` for CI.

**Simplest — `bin/register.sh <type/slug>` from the repo root** finds the entry's
register script and runs it with the right uv invocation, sourcing `.env.dev` for
the gateway URL:

```bash
bin/register.sh datasets/<slug> --upsert   # def-only entry
bin/register.sh agents/<slug>              # packaged entry (builds + publishes a wheel)
```

The invocation depends on whether the entry is a **package**:

- **Packaged** (has its own `pyproject.toml` — agents, tools): the register script
  imports its own package at pre-flight, so it runs **from the package dir** with the
  `publish` group. Its `pyproject.toml` declares the same `[[tool.uv.index]]` so uv
  resolves `techneos-management` there too.
- **Def-only** (datasets, tasks, pipelines, apps): nothing to build — runs from the
  repo root with the `tooling` group.

```bash
uv run --group tooling python datasets/<slug>/register.py            # def-only
( cd agents/<slug> && uv run --group publish python build_and_register.py )   # packaged
```

## Per-package dev (agents, tools)

Each packaged entry is self-contained — its own deps, its own tests:

```bash
cd agents/<slug>
uv sync --group dev
uv run pytest
```

## Removing entries

Each catalog type ships a `bin/<type>_removal.sh` alongside its content — a thin
wrapper around `management.scripts.remove_*` (from the `techneos-management` wheel via
the root `tooling` group) that hits the gateway API and deletes the resource plus
its versions/runs/artifacts. `--dry-run` previews the delete first.

```bash
bin/dataset_removal.sh <slug> --dry-run
bin/agent_removal.sh <slug> --dry-run
```

Removing an agent deletes its `AgentDefinition` row and cascades to its runs; the
wheel on the package index is **not** removed (index retention is a separate concern).

(User removal is platform-admin, not catalog — it stays in the platform repo.)
