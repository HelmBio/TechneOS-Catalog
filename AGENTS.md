# techneos-catalog — agent / contributor guide

This repo holds the platform's registered content (datasets, tools, pipelines,
apps, agents, tasks). It depends on the platform only through published wheels
(`techneos-tool-runtime`, `techneos-management`) from the package index and the gateway REST API —
there is no source dependency on the platform monorepo. See [README.md](README.md)
for the full layout and how the coupling works; each content type gets an
authoring + registration guide under `docs/guides/`, added alongside that type's
first entry.

## Setup

The repo is pinned to Python 3.12 (`.python-version`). The package index is
proxied through the gateway at `{PLATFORM_API_URL}/simple/`; `bin/register.sh`
derives `UV_DEFAULT_INDEX` and `UV_PUBLISH_URL` from `PLATFORM_API_URL` before
invoking uv. Just have the platform's dev stack up and `.env.dev` configured.
(Needs `techneos-management >= 0.1`.)

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
bin/register.sh agents/<slug>              # publishes a wheel
bin/register.sh tools/<slug>               # publishes a wheel, or builds an image
bin/register.sh apps/<slug>                # builds an image + deploys
```

The invocation is chosen from `delivery` in the entry's `[tool.techneos]`:

- **`delivery = "pypi"`** (pypi tools, agents): the register script imports its own
  entry point at pre-flight, so it needs that package's deps (e.g. rdkit) and runs
  **from the package dir** with the `publish` group.
- **everything else** (container tools, and the def-only types — datasets, tasks,
  pipelines, apps): a container tool validates its entry point *statically* and builds
  an image, so its deps live in the image, never on the host. These need only
  `techneos-management` and run from the repo root in an ephemeral, lock-free env
  (`uv run --no-project --with techneos-management`).

## Activating a tool version

Registering a tool does **not** make it runnable. A new version lands as `draft`, and
a run against a tool with no `active` version is rejected (`409`). Transitions are
enforced one step at a time — `draft` cannot jump to `active` — so promote it through
`testing` (via the portal, or `PATCH /api/v1/tools/{id}/versions/{vid}`).

## Per-package dev (agents, tools)

Each packaged entry is self-contained — its own deps, its own tests:

```bash
cd agents/<slug>
uv sync --group dev
uv run pytest
```

## Removing entries

A single `bin/unregister.sh <type> <slug>` handles removal for every catalog type
(`tool`, `agent`, `app`, `dataset`, `task`, `pipeline`) — the counterpart to
`register.sh`. It is a thin wrapper around `management.scripts.remove_*` (from the
`techneos-management` wheel, resolved ephemerally against the per-env gateway index
like `register.sh`) that hits the gateway API and deletes the resource plus its
versions/runs/artifacts. `--dry-run` previews the delete first.

```bash
bin/unregister.sh dataset <slug> --dry-run
bin/unregister.sh agent <slug> --dry-run
bin/unregister.sh app <slug> --dry-run
bin/unregister.sh tool <slug> --dry-run    # optional trailing version: <slug> v2
```

Removing an agent deletes its `AgentDefinition` row and cascades to its runs; the
wheel on the package index is **not** removed (index retention is a separate concern).

(User removal is platform-admin, not catalog — it stays in the platform repo.)
