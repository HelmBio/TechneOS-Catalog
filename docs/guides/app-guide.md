# App Registration Guide

This guide covers the lifecycle for building, registering, and removing Apps on
the TechneOS platform. It uses **Structure Viewer** (Ketcher 2D chemical structure
editor) as the worked example throughout.

Apps in TechneOS are interactive web tools that users launch from the
platform UI. See
`docs/architecture.md#embedded-apps` (in the platform repo) for the runtime
model (sandboxed iframe, runtime proxy, deployer). This guide is about
the **registration and deployment workflow** — how an App definition
moves from a git directory to a live container.

---

## Table of Contents

1. [App Layout](#app-layout)
2. [Launch Modes](#launch-modes)
3. [Lifecycle Overview](#lifecycle-overview)
4. [Structure Viewer — Full Walkthrough](#structure-viewer--full-walkthrough)
5. [Build + Register + Deploy](#build--register--deploy)
6. [Removal](#removal)
7. [Versioning](#versioning)
8. [Adding a New App](#adding-a-new-app)

---

## App Layout

Each App is a self-contained directory under `apps/` at the
repo root. Layout for an `embedded` App:

```
apps/structure-viewer/
├── app_def.json              # full POST /apps body shape (static fields)
├── Dockerfile                # container image build
├── README.md                 # App-level documentation
├── build_and_register.py     # build + register + deploy
├── package.json              # tech stack manifest; `version` drives docker tag
├── next.config.mjs           # framework config (Next.js in this case)
├── src/                      # application source
├── public/                   # static assets served by the App
└── .dockerignore
```

The `app_def.json` mirrors the `POST /api/v1/apps` body, with two
exceptions that are computed at registration time:

| Field          | Where it comes from                     |
|----------------|-----------------------------------------|
| `docker_image` | `techneos/{slug}`                       |
| `docker_tag`   | `package.json` `version` field           |

Everything else (name, slug, category, embed sandbox, health check
path, auth mode, etc.) is static metadata that lives in
`app_def.json`.

> **Removal lives elsewhere.** There's no `remove.py` next to the
> registration script. By convention, all destructive operations live under
> `bin/` (alongside `dataset_removal.sh` and `agent_removal.sh`) so they're
> easy to audit and hard to invoke accidentally. To unregister an App, use
> `bin/app_removal.sh <slug-or-uuid>` — covered in
> [Removal](#removal) below.

---

## Launch Modes

TechneOS supports two launch modes (`packages/core/src/core/models/app.py` in the
platform repo):

| Mode       | Where it runs                          | Auth path                                | When to use                              |
|------------|----------------------------------------|------------------------------------------|------------------------------------------|
| `external` | Anywhere off-platform                  | App's own (or signed-JWT handoff)        | Existing third-party tools we link to    |
| `embedded` | Docker container on the platform host  | Platform session cookie via runtime proxy| Self-contained tools we ship             |

`embedded` Apps are deployed by `app_service.deployer` and reverse-proxied
at `/api/v1/apps/runtime/{slug}/`. The runtime proxy strips that prefix
before forwarding, so the container's framework serves all routes at root.

This guide focuses on the `embedded` flow since `external` Apps don't
need a build or deploy — only the API registration step.

---

## Lifecycle Overview

```
                  ┌──────────────────────────────┐
                  │  build_and_register.py       │
                  │   → management.catalog       │
  apps/           │     .register_app            │
  structure-     ─┼─►1. docker build             │
  viewer/         │  2. record image artifact    │ ──► compute_artifacts
                  │  3. POST  /apps              │ ──► Platform DB
                  │     PATCH /apps/{id}         │     (App row)
                  │  4. POST  /apps/{id}/deploy  │ ──► app-service deployer
                  └──────────────────────────────┘         │
                                                            ▼
                                                  stop old container
                                                  run new container
                                                  probe /healthz

                  ┌──────────────────────────────┐
                  │  bin/app_removal.sh <slug>   │
                  │                              │
                  │  1. DELETE /apps/{id}        │ ──► app-service deployer
                  └──────────────────────────────┘         │
                                                            ▼
                                                  stop + remove container
                                                  drop App row
```

The build/register/deploy steps live in **one script per app** under
`apps/<slug>/`, so releasing an App touches nothing else. Removal lives under
`bin/` with the other destructive operations (`dataset_removal.sh`,
`agent_removal.sh`) — one consistent place to audit anything that deletes
platform state.

---

## Structure Viewer — Full Walkthrough

End-to-end registration into a local platform. It assumes the platform's dev stack
is already running (gateway + app-service) and Docker is available.

### Step 1: Build + Register + Deploy

```bash
bin/register.sh apps/structure-viewer
```

The script is constants plus a single `management.catalog.register_app` call:
1. Reads `version` from `package.json` (the image tag); authenticates via
   `start_session` (cached JWT under `~/.techneos/{env}_token.json`, else prompts).
2. `build_image_and_record` runs `docker build` and records the image in
   `compute_artifacts` (`origin=catalog`; non-fatal, since app registration doesn't
   hard-validate against the inventory).
3. Upserts the App (`POST /api/v1/apps`, or PATCH `docker_image`/`docker_tag` on an
   existing row; `--upsert` recreates).
4. `POST /api/v1/apps/{id}/deploy` — the app-service deployer stops any existing
   `techneos-app-structure-viewer` container, runs a fresh one, and probes `/healthz`.

### Step 2: Verify

Open `http://localhost:3000/apps` — the App should appear with
`status=ready` once the deployer finishes its health-probe loop
(typically 5–15 seconds).

---

## Build + Register + Deploy

`build_and_register.py` runs the three phases in sequence, with flags to
skip any of them.

### Common invocations

```bash
# Full flow
bin/register.sh apps/structure-viewer

# Re-deploy without rebuilding (image already on the host)
bin/register.sh apps/structure-viewer --skip-build

# Register/update the App row without triggering a deploy
bin/register.sh apps/structure-viewer --skip-deploy

# Force re-create the App row (DELETE then POST)
bin/register.sh apps/structure-viewer --upsert
```

### Flag reference

| Flag             | Effect                                                                                     |
|------------------|--------------------------------------------------------------------------------------------|
| `--upsert`       | If an App with this slug exists, delete and recreate. Otherwise, PATCH the existing row.   |
| `--skip-build`   | Don't run `docker build`. Use when the image is already built locally.                     |
| `--skip-deploy`  | Don't call `POST /apps/{id}/deploy`. The App row is created/updated but no container runs. |
| `--email`        | Admin email; prompted if omitted.                                                          |
| `--password`     | Admin password; prompted if omitted.                                                       |

### Authentication

`build_and_register.py` resolves a JWT itself. The order of preference is:

1. **Cached token** at `~/.techneos/{env}_token.json` (auto-written on a
   successful login; reused until expiry).
2. **Interactive prompt** for admin email + password, or
   `--email`/`--password` flags for non-interactive flows like CI.

For ad-hoc API calls outside the script (e.g. `curl`), the cached
token is plain JSON — `jq -r .access_token ~/.techneos/development_token.json`
reads it.

### Idempotency

The registration step is idempotent. On the second run:

- If no App with the slug exists: `POST /apps` to create it.
- If one exists: `PATCH /apps/{id}` to update `docker_image` and
  `docker_tag` only. Other metadata (name, description, tags, ...) is
  preserved so manual edits in the web portal aren't clobbered.

Use `--upsert` when you want a clean slate (e.g., to pick up changes
to fields you don't normally PATCH like `embed_sandbox` or `auth_mode`).
That deletes the existing row, which stops the running container, and
then re-creates from scratch.

---

## Removal

Removal lives under `bin/` alongside `dataset_removal.sh` and
`agent_removal.sh`. The script accepts a slug or a UUID — the same wrapper
works for any App, not just structure-viewer:

```bash
./bin/app_removal.sh structure-viewer

# Preview without changes
./bin/app_removal.sh structure-viewer --dry-run

# No confirmation prompt
./bin/app_removal.sh structure-viewer --yes

# Remove by UUID
./bin/app_removal.sh 2a092397-22bd-476a-b379-7ba41f2103b6
```

Flags:

| Flag           | Effect                                                                          |
|----------------|---------------------------------------------------------------------------------|
| `--dry-run`    | Resolve the App and show the summary, but don't call DELETE.                    |
| `--yes`, `-y`  | Skip the interactive confirmation prompt.                                       |

What it does:
1. Resolves the App by slug or UUID. If not found, exits non-zero.
2. Prints a summary (id, slug, launch_mode, runtime_status, image+tag)
   and reports any active launches.
3. Prompts for confirmation unless `--yes` or `--dry-run`.
4. Calls `DELETE /api/v1/apps/{id}`, which the app-service handles by:
   - Enqueuing a `stop` for the running container (no-op if not running)
   - Deleting the App row (cascades to AppLaunch records)

What it does **not** do:
- Remove the Docker image. Image lifecycle is a deployment concern, handled by
  the registry's retention rules.
- Remove the image from the host's local cache. `docker image prune`
  is the right tool for that.

The wrapper is a thin shim — the implementation lives in
`packages/management/src/management/scripts/remove_app.py` (in the platform repo),
following the same pattern as the other `*_removal.sh` scripts.

---

## Versioning

App version is the **single source of truth** in `package.json`:

```json
{
  "name": "structure-viewer",
  "version": "0.1.0",
  ...
}
```

`build_and_register.py` reads it directly. To release a new version:

1. Update `package.json` version (e.g., `0.1.0` → `0.2.0`).
2. Re-run `build_and_register.py`. The image is built with the new
   tag, and the App row's `docker_tag` is PATCHed to match.
3. `/deploy` is called automatically (unless `--skip-deploy`), which
   stops the old container and starts the new one.

There is no separate "app version" entity in the API (unlike
`/datasets/{id}/versions`). Apps have a single docker image + tag, and
replacing it is the only update path.
Roll back by setting `package.json` version to the previous tag and
re-running.

---

## Adding a New App

To add a new App to the platform, create a new directory under
`apps/`:

```
apps/your-app-name/
├── app_def.json              # static POST /apps body
├── Dockerfile                # multi-stage Next.js build (or your framework)
├── README.md                 # what this App does and how to use it
├── build_and_register.py     # copy from structure-viewer/, edit APP_DIR-relative paths
├── package.json              # version field drives the docker tag
├── next.config.mjs           # (or your framework's config)
└── src/ public/ ...          # your application source
```

Removal is handled by the shared `bin/app_removal.sh <slug>` — no
per-app removal script is needed. The wrapper works for any App
because it looks the resource up by slug or UUID.

Minimum required `app_def.json` for an `embedded` App:

```json
{
  "name": "Your App",
  "slug": "your-app-name",
  "description": "What it does.",
  "category": "general",
  "launch_mode": "embedded",
  "container_port": 3000,
  "health_check_path": "/healthz",
  "auth_mode": "none",
  "is_public": false
}
```

`build_and_register.py` is mostly boilerplate — copy from
`apps/structure-viewer/` and the only edits needed are:

- The slug-derived paths (the script reads everything else from
  `app_def.json`).
- Any framework-specific build args (e.g., `APP_BASE_PATH` in the
  Dockerfile for Next.js).

Once the directory is in place, `bin/register.sh apps/<slug>` is enough to ship it.

### Health check contract

The app-service deployer probes `health_check_path` (default `/healthz`)
until it returns 200 before marking the App `ready`. Your framework's
default root path usually works for static apps; explicit `/healthz`
is recommended for anything dynamic. For Next.js, expose it via a
route handler at `app/healthz/route.ts`:

```ts
export const GET = () => Response.json({ ok: true });
```

### Runtime proxy contract

The runtime proxy strips `/api/v1/apps/runtime/{slug}/` from incoming
URLs, so your container sees plain paths (`/`, `/healthz`, `/static/foo`).
Outgoing HTML must point at the prefixed URL for static assets — for
Next.js, set `assetPrefix` (not `basePath`) at build time via an env
var. The structure-viewer Dockerfile shows the pattern.

---

## See Also

- [Dataset Registration Guide](dataset-guide.md) — Registering and versioning datasets (ZINC20 example)
- [Tool Registration Guide](tool-guide.md) — Registering computational tools (pypi and container)
- [Agent Building Guide](agent-guide.md) — Building and deploying AI agents
- [Task Guide](task-guide.md) — Authoring and registering human tasks (offline work for a person or team)
- [Pipeline Building Guide](pipeline-guide.md) — Chaining tools into DAG workflows (hit-triage example)
