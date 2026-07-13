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
bin/register.sh datasets/<slug> --upsert
```

Or invoke uv directly — a dataset registers through `techneos-management` (the root
`tooling` group), with no wheel or image to build:

```bash
uv run --group tooling python datasets/<slug>/register.py
```

## Removing entries

Each catalog type ships a `bin/<type>_removal.sh` alongside its content — a thin
wrapper around `management.scripts.remove_*` (from the `techneos-management` wheel via
the root `tooling` group) that hits the gateway API and deletes the resource plus
its versions/runs/artifacts. `--dry-run` previews the delete first.

```bash
bin/dataset_removal.sh <slug> --dry-run
```

(User removal is platform-admin, not catalog — it stays in the platform repo.)
