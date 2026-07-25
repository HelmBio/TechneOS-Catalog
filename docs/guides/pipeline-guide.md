# Pipeline Building Guide

This guide covers defining, executing, and monitoring computational pipelines on
the TechneOS platform. It uses the catalog's **Hit Triage** pipeline
(`structure-alerts` → `compound-clustering` → `autodock-vina`) as the worked
example throughout.

---

## Table of Contents

1. [Pipeline Concepts](#pipeline-concepts)
2. [Defining a Pipeline](#defining-a-pipeline)
3. [Hit Triage — Full Walkthrough](#hit-triage--full-walkthrough)
4. [Submitting a Run](#submitting-a-run)
5. [Monitoring Runs](#monitoring-runs)
6. [Data I/O — Datasets & Upstream Artifacts](#data-io--datasets--upstream-artifacts)
7. [Artifacts & Downloads](#artifacts--downloads)
8. [Execution Model](#execution-model)
9. [Compute Backends](#compute-backends)
10. [Events & Notifications](#events--notifications)
11. [Best Practices](#best-practices)
12. [See Also](#see-also)

---

## Pipeline Concepts

A pipeline is a **directed acyclic graph (DAG)** of computational steps. Each
step invokes a registered tool (see [Tool Registration Guide](tool-guide.md))
with specific parameters.

| Concept | Description |
|---------|-------------|
| **Shape** | The canonical DAG: step names, `tool_slug`s, `depends_on`/edges, inter-step `inputs` wiring, and the run-I/O `parameters_schema`. Lives on the **`pipelines`** row and is the pipeline's identity. |
| **Binding** | What a **version** pins/tunes: `{ step_name → { tool_version, parameters } }`. Lives on the **`pipeline_versions`** row. |
| **Topology hash** | SHA-256 of the normalized shape — the structural fingerprint used for identity, dedup, and drift detection. |
| **Step** | A single computation — identified by a name and a `tool_slug` (part of the shape). |
| **Edge** | A dependency link from one step to another (`from_step` → `to_step`). |
| **Parameters schema** | JSON Schema describing the run-time inputs users provide; per-property `default`s carry run-input defaults. |
| **Run** | A single execution of a pipeline version with concrete parameter values. |
| **Step run** | The execution record for one step within a run. |
| **Artifact** | A run file stored in MinIO — a staged **input** or a step **output**, distinguished by `io_type` on the `pipeline_run_artifacts` row. |

### Shape vs. binding

A pipeline's identity is **slug + topology**: the DAG *shape* is **immutable** and
owned by the parent `pipelines` row. A **version** never redraws the graph — it is
a *binding* that only **pins which tool version runs at each step and the
parameter values used**. Run reproducibility = `(topology_hash + per-step
tool_version + parameters)`. To change the topology — add, remove, or rewire a
step, swap a tool slug, change the run-input contract — **fork** the pipeline
(`POST /pipelines/{id}/fork`), which copies the shape into a new pipeline with a
`forked_from` lineage pointer, rather than cutting a new version.

**Pipeline type ↔ tool kinds.** The `pipeline_type` must match the kinds of tools
in the DAG, enforced on create/update: `compute` = every tool is `pypi`/`container`,
`interactive` = every tool is `human`, `hybrid` = any other mix. Hit Triage is a
`compute` pipeline — all three tools are `pypi`/`container`.

### DAG Example

Hit Triage is a linear three-stage graph:

```
screen_alerts ──► cluster_compounds ──► dock_vina
```

Steps with no incoming edges run in parallel. Steps with dependencies wait until
all upstream steps complete.

---

## Defining a Pipeline

### Via Catalog (`pipelines/`)

The catalog is the primary way to define a pipeline: it gets the same admin-auth,
version-controlled lifecycle as the other catalog types. Each pipeline is a folder
with a `pipeline_def.json` (the single source of truth — steps, edges,
`parameters_schema`, declarative `inputs`), a `register.py` (no build step — a
pipeline has no artifact), and optional `examples/`. The reference implementation
is `pipelines/hit-triage`:

```bash
# register / update
bin/register.sh pipelines/hit-triage --upsert

# remove (cascades versions/runs); --dry-run to preview, --force to cancel active runs
bin/unregister.sh pipeline hit-triage
```

`register.py` preflights that the referenced tools are registered and **active**
(the service rejects creation otherwise), then registers the definition via
`management.catalog.register_pipeline`. `bin/unregister.sh pipeline` wraps
`management.scripts.remove_pipeline` and removes any pipeline by slug.

### Via API

The create endpoint accepts an **ergonomic inline form** — steps carrying
`tool_version` + `parameters` — and **splits it server-side** into the parent
*shape* plus a v1 *binding*:

```bash
curl -X POST http://localhost:8000/api/v1/pipelines \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Hit Triage",
    "slug": "hit-triage",
    "description": "Screen, cluster, and dock a compound set.",
    "steps": [
      {
        "name": "screen_alerts",
        "tool_slug": "structure-alerts",
        "parameters": {"filter_catalogs": ["PAINS", "BRENK"], "include_passing": true},
        "depends_on": []
      },
      {
        "name": "cluster_compounds",
        "tool_slug": "compound-clustering",
        "parameters": {"method": "butina", "cutoff": 0.35},
        "depends_on": ["screen_alerts"],
        "inputs": {
          "compounds": {"from_step": "screen_alerts", "path": "results", "filter": {"passed": true}}
        }
      },
      {
        "name": "dock_vina",
        "tool_slug": "autodock-vina",
        "parameters": {"exhaustiveness": 8},
        "depends_on": ["cluster_compounds"],
        "inputs": {
          "compounds": {"from_step": "cluster_compounds", "path": "results", "filter": {"is_representative": true}}
        }
      }
    ],
    "edges": [
      {"from_step": "screen_alerts", "to_step": "cluster_compounds"},
      {"from_step": "cluster_compounds", "to_step": "dock_vina"}
    ],
    "parameters_schema": {
      "type": "object",
      "properties": {
        "compounds": {"type": "array", "x-input": true, "x-step": "screen_alerts"},
        "receptor": {"type": "string", "x-input": true, "x-step": "dock_vina"}
      },
      "required": ["compounds", "receptor"]
    },
    "tags": ["hit-triage", "docking"],
    "is_public": true
  }'
```

After creation the shape is fixed — new versions submit `bindings` only. Run-input
defaults go on `parameters_schema` property `default`s (which the run form renders
as pre-filled widgets).

### Via Web Portal

1. Navigate to **Pipelines** in the sidebar
2. Click **Create Pipeline**
3. Fill in the **Pipeline Metadata** section:
   - **Name**, **Slug** (auto-generated, URL-safe, unique), **Description**,
     **Tags**, **Public** toggle
   - **Category** and **Type** (`compute` / `interactive` / `hybrid`), and a
     Markdown **README** — mirroring the tool metadata model
4. Define **Steps** (the shape — fixed once the pipeline is created):
   - Each step has a **name**, **tool** (dropdown of registered tools with a type
     badge), and **version** (dropdown of the tool's versions, or "latest")
   - Add **parameters** via the schema-driven editor (booleans, single/multi
     enums render as pick lists; numbers accept decimals) or raw JSON
   - Set **depends_on** by toggling dependency buttons for other steps
5. A **type validation** panel checks `pipeline_type` against the selected tools'
   kinds and offers a one-click fix on mismatch
6. Optionally define the **Parameters Schema** (run-input contract); run-input
   defaults live on each property's `default`
7. Click **Create Pipeline**

> **Tip**: Use the **DAG Preview** panel to visualize the step graph as you build
> it. Steps and edges update in real time.

#### Editing a Pipeline

The pipeline detail page separates **metadata**, **shape**, and **bindings**:

- **Update Pipeline Definition** (pencil in the header) — a modal where metadata
  (description, category, type, tags, public, README) is editable while the **DAG
  and Run inputs are shown locked**. It PATCHes the `pipelines` row and **does not
  create a version**.
- **+ New Version** (Versions section header) — opens the version editor modal: a
  **bindings-only** form over the locked shape. Per step you pick the
  **tool-version pin** and **expose/tune parameters** (schema-driven pick lists);
  submit creates a new version. It never changes the topology.
- **Update this version** (pencil on a version card) — edit a **draft/testing**
  version's bindings **in place** while it has no runs. Once a version is
  `active`/`deprecated` or has runs, its binding is frozen — create a new version.
- **Evolving the topology** requires a **fork** (`POST /pipelines/{id}/fork`).
- **Duplicate** (header action) — opens the new-pipeline form pre-filled from this
  pipeline's shape as an independent copy (name suffixed "(copy)"), leaving the
  original untouched. It's a starting point for a hand-edited variant, distinct
  from a fork's tracked `forked_from` lineage. A pipeline is a pure definition
  with no artifact, so a copy stands on its own — unlike a tool, which is backed by
  a published wheel or image and so has no duplicate action.

### Required Fields

| Field | Rules |
|-------|-------|
| `name` | 1–255 characters |
| `slug` | Lowercase alphanumeric + `.`, `-`, `_`. Unique |
| `steps` | At least one step. Each needs `name` and `tool_slug` |

### Step Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier within the pipeline |
| `tool_slug` | Yes | References a registered tool |
| `tool_version` | No | Specific version number. **If omitted or `null`, the version's binding pins the currently-active version at save time** — the shape keeps the abstract reference, but the saved binding carries a concrete number so the pipeline can't silently change behaviour when a newer tool version activates. Use `track_latest: true` to opt out (resolve at dispatch time instead). |
| `track_latest` | No | If `true`, leave `tool_version` unset and resolve "latest active" at every dispatch. Default `false` (pin). |
| `tool_type` | No | Tool type (`container`, `pypi`, `api`). Auto-resolved from the tool registry if omitted. |
| `parameters` | No | Step-level default parameters |
| `depends_on` | No | List of step names this step depends on |
| `inputs` | No | Map a named tool input to an upstream step's output — `{"<field>": {"from_step": "...", "path": "...", "filter": {...}}}`. See [Declarative Inputs](#declarative-inputs-upstream-output--a-named-tool-input). |

### Edge Fields

| Field | Required | Description |
|-------|----------|-------------|
| `from_step` | Yes | Source step name |
| `to_step` | Yes | Target step name |

---

## Hit Triage — Full Walkthrough

End-to-end registration and a run against a local platform. It assumes the
platform's dev stack is already running (gateway, pipeline service, and the Airflow
execution layer) per the platform repo's README, and that the three tools are
registered and **active** — see the [Tool Registration Guide](tool-guide.md).

### Step 1: Register

```bash
bin/register.sh pipelines/hit-triage --upsert
```

The pre-flight checks that `structure-alerts`, `compound-clustering`, and
`autodock-vina` each have an active version, then registers the DAG. Output prints
the pipeline id, the API URL, and the portal URL.

### Step 2: Submit a run

Open the pipeline detail page and click **▶ Run** on the active version to open the
**Submit Run** wizard. Hit Triage declares two `x-input` fields:

- **compounds** (assigned to `screen_alerts`) — paste or upload the list of
  `{smiles, id}` objects. `pipelines/hit-triage/examples/compounds.json` is a
  ready-made set that includes a deliberate PAINS flag.
- **receptor** (assigned to `dock_vina`) — upload a PDB.
  `pipelines/hit-triage/examples/5VAI_GLP-1R.pdb` is provided;
  `bin/fetch_receptor.sh <PDB_ID>` fetches others into that directory.

### Step 3: Watch it run

The run detail page shows the DAG with per-step status, updating live over SSE.
The three stages run in sequence: `screen_alerts` keeps the clean compounds,
`cluster_compounds` groups the survivors and marks one representative per family,
and `dock_vina` docks the representatives into the receptor and ranks them by
predicted affinity. Each stage's output artifacts appear grouped by step name,
downloadable individually or as a ZIP.

---

## Submitting a Run

### Via API

```bash
curl -X POST http://localhost:8000/api/v1/pipeline-runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "pipeline_id": "<PIPELINE_ID>",
    "parameters": {
      "compounds": [{"smiles": "CC(=O)Oc1ccccc1C(=O)O", "id": "aspirin"}],
      "receptor": "receptor.pdb"
    }
  }'
```

The response includes a `run_id`. The orchestrator dispatches the run to Airflow,
which creates a DAG run and begins executing steps. File inputs (`compounds` if
uploaded, `receptor`) are staged first via `POST /pipeline-runs/inputs`, exactly as
the run wizard does it.

### Via Web Portal

1. Navigate to the pipeline detail page (`/pipelines/{id}`)
2. Click **▶ Run** on a runnable (active/testing) version's header to open the
   **Submit Run** wizard (scoped to that version)
3. The wizard is a **train-stops stepper** — a Pipeline stop followed by one stop
   per step. Each stop shows up to two sections, as needed:
   - **Input data** — schema fields flagged `x-input` (and assigned to a step via
     `x-step`) render the same **Dataset / Upload / Paste** widget as the tool-run
     form. Uploads/pastes are staged via `POST /pipeline-runs/inputs` (MinIO scratch
     space). On submit the service relocates each file to the run's
     `pipeline-runs/{slug}/v{N}/{run_id}/inputs/` prefix, records a
     `pipeline_run_artifacts` row with `io_type='input'` tagged with its owning
     step, and injects a namespaced typed pointer (`<step>.<field>`) the worker
     resolves.
   - **Parameters** — the step's tunable parameters, pre-filled with defaults, sent
     as namespaced parameters (`step_name.param_key`).

   The Pipeline stop also holds the optional run name. Stops are clickable to jump;
   missing required inputs send you to the owning stop.
4. Click **Submit** on the final stop
5. You are redirected to the run detail page

### Run Statuses

| Status | Meaning |
|--------|---------|
| `pending` | Run created, waiting for Airflow dispatch |
| `running` | At least one step is executing |
| `completed` | All steps finished successfully |
| `failed` | One or more steps failed |
| `cancelled` | User cancelled the run |

---

## Monitoring Runs

### Run List (`/pipeline-runs`)

A paginated table with Run ID, Pipeline, Version, Status (color-coded), Submitted
By, Organization, Submitted timestamp, and Duration. It supports a status-filter
dropdown, configurable page size (10/15/25/50), and page navigation.

### Run Detail (`/pipeline-runs/{id}`)

- **Status badge** with live updates (SSE + polling fallback every 5s)
- **Pipeline graph**: visual DAG with step statuses color-coded
- **Info grid**: pipeline name, submitter, org, timestamps, Airflow DAG/run IDs
- **Error display**: if the run failed, the error message is shown prominently
- **Step cards**: each step shows status icon, duration, and a "View logs" button
  that fetches Airflow task logs
- **Parameters**: the input parameters used for this run
- **Artifacts table**: output files with name, size, content type, and a
  **Download** button (presigned MinIO URL)
- **Artifact file tree**: artifacts grouped by step name as collapsible folders;
  individual files download with the step name prefixed (e.g.
  `dock_vina_result.json`). A **Download All (ZIP)** button packages everything by
  step folder.
- **Cancel button**: stops the Airflow DAG run (available while running)

### SSE Streaming

The run detail page uses Server-Sent Events for real-time updates:

```
GET /api/v1/pipelines/runs/{run_id}/events
Accept: text/event-stream
```

Events are pushed when step statuses change or the run completes/fails.

### Auto-Sync

When you fetch a run via `GET /api/v1/pipeline-runs/{run_id}`, the server
automatically syncs the latest status from Airflow if the run is still active
(`pending`/`running`), or is terminal but all steps are still `pending` (stale
data). Force a manual sync:

```bash
curl -X POST http://localhost:8000/api/v1/pipeline-runs/{run_id}/sync \
  -H "Authorization: Bearer $TOKEN"
```

### Step Logs & Cancel

```bash
# Logs for one step
curl http://localhost:8000/api/v1/pipeline-runs/{run_id}/steps/{step_name}/logs \
  -H "Authorization: Bearer $TOKEN"

# Cancel a running pipeline
curl -X POST http://localhost:8000/api/v1/pipeline-runs/{run_id}/cancel \
  -H "Authorization: Bearer $TOKEN"
```

The logs endpoint returns, in priority order: container logs stored in the step
run's `outputs.logs_tail`, then the Airflow task logs, then
`"No logs available yet."`.

---

## Data I/O — Datasets & Upstream Artifacts

Pipeline steps can consume **registered datasets** and **output artifacts from
upstream steps**. The platform downloads data from MinIO and bind-mounts it into
the container before execution.

### Dataset Parameters

Any step parameter named `dataset`, `dataset_id`, or ending with `_dataset` /
`_dataset_id` is treated as a dataset reference:

- **Slug with version**: `zinc20:v1`
- **Slug** (latest version): `zinc20`
- **UUID with version**: `{dataset_id}:v2`
- **UUID** (latest version): `{dataset_id}`

The worker resolves the reference via the dataset service's `/resolve-storage`
endpoint, downloads the file from MinIO, and mounts it into the container.

### Container Mount Points

All inputs are staged under the `/work/` mount; the worker records their resolved
paths in `/work/inputs.json` for the tool to read.

| Source | Container path | Example |
|--------|---------------|---------|
| `dataset` or `dataset_id` param | `/work/input/{filename}` | `/work/input/zinc20.txt` |
| Upstream step output | `/work/input/upstream/{step}/{filename}` | `/work/input/upstream/screen_alerts/result.json` |

### Declarative Inputs (upstream output → a named tool input)

The mount-point convention hands a downstream tool its predecessor's files under
`inputs["upstream"]`. But most tools read a specific named input (e.g. `compounds`),
and an upstream tool's `result.json` is rarely already in that shape. The **`inputs`**
step field wires the two together declaratively — no tool changes required:

```json
{
  "name": "cluster_compounds",
  "tool_slug": "compound-clustering",
  "depends_on": ["screen_alerts"],
  "inputs": {
    "compounds": {
      "from_step": "screen_alerts",
      "file": "result.json",
      "path": "results",
      "filter": { "passed": true }
    }
  }
}
```

| Key | Required | Description |
|-----|----------|-------------|
| `from_step` | Yes | Name of the upstream step whose output supplies this input |
| `file` | No | Artifact file name from that step (default `result.json`) |
| `path` | No | Dotted path to a list inside the output JSON (e.g. `results`). Omit if the output is already a list |
| `filter` | No | Keep only list rows where every `key: value` matches (e.g. `{"passed": true}`) |

At dispatch the worker downloads the named upstream artifact, navigates `path` to a
list, applies `filter`, and writes the result straight into `inputs.json[<field>]`.
The tool then reads `inputs["<field>"]` directly — so any upstream JSON shape can
feed any downstream tool. Hit Triage uses this twice: `screen_alerts` survivors
(`results` where `passed: true`) → clustering, and clustering representatives
(`results` where `is_representative: true`) → docking.

> Each step receives only its own namespaced params (`<step>.<key>`) plus
> truly-global params — one step's namespaced params (including typed-pointer inputs
> like an uploaded receptor) are not visible to other steps.

### Shared Volume (Local Dev)

In local development the Airflow scheduler runs inside a container but creates
**sibling** tool containers via the host's Docker socket. To pass downloaded files
between them, a shared volume is mounted (host `.dev-tmp/inputs/` ↔ scheduler
`/tmp/techneos-shared-inputs/`), configured in `docker-compose.yml` via
`TECHNEOS_SHARED_INPUT_DIR` / `TECHNEOS_HOST_SHARED_INPUT_DIR`.

---

## Artifacts & Downloads

Steps produce output files that are collected as artifacts:

1. The Airflow worker runs the tool container.
2. After it completes, the worker collects output files from `/work/output/`.
3. Files are uploaded to MinIO (`techneos-data` bucket) under the run's prefix.
4. The worker registers each artifact via the platform API with metadata (file
   name, size, content type, SHA-256 checksum).

### Download

```bash
# Get a presigned download URL
curl http://localhost:8000/api/v1/pipeline-runs/{run_id}/artifacts/{artifact_id}/download \
  -H "Authorization: Bearer $TOKEN"

# Response: {"download_url": "http://localhost:9000/techneos-data/pipeline-runs/{pipeline_slug}/v{N}/{run_id}/{step_name}/{file}?X-Amz-..."}
```

In the portal, artifacts are a **file tree** grouped by step name. Individual
downloads are prefixed with the step name; **Download All (ZIP)** packages
everything (`run-{id}-artifacts.zip`) into per-step folders.

---

## Execution Model

The platform runs pipelines on **Apache Airflow**, which handles scheduling,
retries, and log collection. The DAG definition lives in the platform repo
(`packages/execution/dags/`), not the catalog — a catalog author never edits it.

1. The **Pipeline Service** orchestrator calls the Airflow REST API to trigger a
   DAG run with a `conf` payload containing the step configurations.
2. A single orchestration task walks the full step graph:
   - Steps are topologically sorted into **execution tiers** based on `depends_on`.
   - Steps within a tier run **concurrently**; tiers execute **sequentially**.
   - If any step in a tier fails, remaining tiers are **skipped** and reported as
     `skipped` to the platform API.
   - Cycle detection runs before execution — a cycle raises an error immediately.
3. Each step runs via the **ToolOperator**, which resolves `tool_type` from the
   registry, dispatches to a [compute backend](#compute-backends), polls for
   completion, collects output artifacts from `/work/output/`, uploads them to
   MinIO, and reports step status back via callback.

### Parameter Propagation

1. **Global parameters** are applied to all steps as defaults — step-level values
   take precedence.
2. **Namespaced parameters** (e.g. `dock_vina.exhaustiveness`) are applied only to
   the named step, with the prefix stripped.
3. The resolved per-step dict is written verbatim to `/work/params.json`; the tool
   reads it via `run(inputs, params)` (no coercion — lists, numbers, and nested
   objects pass through as JSON).

### Failure Reporting

When a container exits non-zero, the Docker backend captures the last lines of
container logs and includes them in the error message — you see the actual
traceback instead of just "Exit code 1". The ToolOperator reports status changes
via `PATCH /api/v1/pipeline-runs/{run_id}/steps/{step_name}/status`.

---

## Compute Backends

The ToolOperator dispatches each step to a compute backend:

- **Docker (development)** — the default locally. Creates a container from the
  tool's image (`techneos/{tool_slug}` for container tools, `techneos/tool-runtime`
  for pypi tools), bind-mounts the host work dir at `/work`, waits for completion,
  reads `/work/output/` from the host, and cleans up.
- **AWS Batch (cloud)** — submits a job to a Batch queue, polls for completion, and
  collects outputs from the job's output location. Selected by configuration when
  the platform runs in the cloud.

---

## Events & Notifications

The pipeline service publishes events via **EventBus** (Valkey pub/sub) so other
services — in particular the notification service — can react without tight
coupling. If EventBus is unavailable, it falls back to a direct HTTP POST to the
notification service's `/internal/notify`.

### Published Events

| Channel | Trigger | Payload fields |
|---------|---------|----------------|
| `pipeline.created` | A new pipeline definition is created | `pipeline_id`, `pipeline_name`, `pipeline_slug`, `org_id`, `user_id` |
| `pipeline.updated` | A pipeline definition is updated | `pipeline_id`, `pipeline_name`, `version` |
| `pipeline.version.created` | A new pipeline version is published | `pipeline_id`, `pipeline_name`, `pipeline_slug`, `version`, `changelog` |
| `pipeline.run.completed` | A run transitions to `completed` | `run_id`, `pipeline_id`, `pipeline_name` |
| `pipeline.run.failed` | A run transitions to `failed` | `run_id`, `pipeline_id`, `pipeline_name`, `error` |

Users **subscribe** to a pipeline (`POST /api/v1/notifications/subscriptions` with
`resource_type=pipeline`); when an event fires, the notification service creates an
in-app notification for each subscriber, surfaced on the portal's bell icon.

---

## Best Practices

### Pipeline Design

- Keep step names short and descriptive (`screen_alerts`, not `step_1`).
- Use `depends_on` to express real data dependencies — don't serialize steps
  unnecessarily.
- Maximize parallelism: independent steps should have no edges between them.

### Parameters

- Define a `parameters_schema` with `required` fields for user inputs.
- Put run-input defaults on each property's `default`; per-step defaults are the
  binding's `parameters`.
- Use `description`, `enum`, and types in the schema — the run form renders typed
  widgets (enum → pick list, array-of-enum → multi-pick) from them.

### Tool References

- Use `tool_slug` to reference tools; the engine resolves the image as
  `techneos/{tool_slug}` for container tools.
- **Pin `tool_version`** for reproducibility. If you omit it on save, the pipeline
  service resolves the currently-active version and writes that concrete number
  into the version's binding — so a run always executes a pinned version, even
  though the shape keeps the abstract reference.
- For "always follow latest active" semantics, set `track_latest: true` on the
  step. Use sparingly — a tool activation elsewhere can then silently change your
  pipeline's behaviour.

### Artifacts

- Tools should write output files to `/work/output/` inside the container.
- Use standard formats: JSON for structured data, CSV for tabular data.
- Include a `result.json` summary for programmatic consumption — it is the default
  file the declarative `inputs` wiring reads from.

---

## See Also

- [Tool Registration Guide](tool-guide.md) — Registering the tools a pipeline's steps invoke
- [Dataset Registration Guide](dataset-guide.md) — Registering datasets consumed by pipelines
- [Agent Building Guide](agent-guide.md) — Building AI agents
- [App Registration Guide](app-guide.md) — Building and deploying embedded apps
- [Task Guide](task-guide.md) — Authoring and registering human tasks
