# Tool Registration Guide

This guide covers the complete lifecycle for registering, versioning, and
discovering computational tools on the TechneOS platform. It uses the catalog's
**Molecule Property Calculator**, **Dataset Profiler**, and **Structure Alerts** as
worked examples.

---

## Table of Contents

1. [Tool Types](#tool-types)
2. [Registering a Tool](#registering-a-tool)
3. [Creating Versions](#creating-versions)
4. [Version Lifecycle](#version-lifecycle)
5. [Defining Schemas](#defining-schemas)
6. [Subscription & Notifications](#subscription--notifications)
7. [Running a Tool Directly](#running-a-tool-directly)
8. [Tool Execution Model](#tool-execution-model)
9. [Using Tools in Agents](#using-tools-in-agents)
10. [Web Portal Walkthrough](#web-portal-walkthrough)
11. [Molecule Property Calculator Example — Pypi Tool with Agent Surface](#molecule-property-calculator-example--pypi-tool-with-agent-surface)
12. [Dataset Profiler Example — Container Tool](#dataset-profiler-example--container-tool)
13. [Structure Alerts Example — Pypi Tool](#structure-alerts-example--pypi-tool)
14. [Best Practices](#best-practices)

---

## Tool Types

TechneOS supports three tool types:

| Type        | Description                                        | Example                     |
|-------------|----------------------------------------------------|-----------------------------|
| `container` | Dedicated Docker image built on `techneos/tool-runtime` | Dataset Profiler, AutoDock Vina |
| `pypi`      | Python package pip-installed from a package index  | Molecule Property Calculator, Structure Alerts |
| `api`       | External API endpoint (SaaS or institutional)      | AlphaFold Server, PubChem (future) |

The `tool_type` field determines how the tool is packaged and executed:

- **container**: runs in a dedicated Docker image built on
  `techneos/tool-runtime`; the tool installs any extra native deps it needs in its
  own Dockerfile (e.g. WeasyPrint's Pango/Cairo libs, or AutoDock Vina +
  OpenBabel). The base provides the
  `python -m techneos_tool_runtime.runner` entrypoint; your image sets
  `ENTRYPOINT_SPEC=module.path:run` and pip-installs the tool package.
  The runner reads `/work/inputs.json` + `/work/params.json` and calls your
  `run(inputs, params) -> dict`.
- **pypi**: a pip-installable Python package published to a package index
  (the local devpi in dev). The
  `techneos/tool-runtime` base image has `techneos-tool-runtime` baked in, so at
  dispatch time the worker only pip-installs the tool package itself,
  then invokes the same runner CLI. No Dockerfile needed.
- **api**: external HTTP calls (future)

---

## Registering a Tool

### Via API

```bash
curl -X POST http://localhost:8000/api/v1/tools \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Molecular Featurizer",
    "slug": "mol-featurizer",
    "description": "Compute molecular fingerprints and descriptors using RDKit",
    "category": "general",
    "tool_type": "pypi",
    "tags": ["cheminformatics", "molecular-descriptors", "fingerprints"],
    "is_public": true
  }'
```

### Via Web Portal

1. Navigate to **Tools** in the top navigation
2. Click **Register Tool** (admin/project-lead role required)
3. Fill in the **Tool Metadata** section:
   - **Name**: Human-readable name (e.g., "Dataset Profiler")
   - **Slug**: URL-safe identifier, auto-generated from name (e.g., "dataset-profiler") — must be unique, cannot be changed after creation
   - **Type**: Select `container`, `pypi`, or `api`
   - **Category**: Select the best fit (`general`, `docking`, `scoring`, `admet`, `ml`)
   - **Tags**: Comma-separated tags for discoverability
   - **README** (Markdown): Tool-level documentation describing what it does
   - **Public**: Toggle on to make visible to all orgs
4. Fill in the **Initial Version (v1)** section:
   - For **container** tools: Docker image name and tag
   - For **pypi** tools: package name, version, entry point (`module.path:function`), and optional package index URL
   - **Resource Requirements**: CPU, memory, GPU
   - **Input/Output/Parameters Schemas**: JSON Schema editors with validation
   - **Changelog** (optional): What changed in this version. Per-version
     provenance (git SHA) goes in the Git Ref field.
   - **Test Script**, **Git Ref** (optional)
   - **Version Status**: Starts as `draft`; promote through `testing` to `active` before it can run
5. Click **Register Tool** to create

### Editing a Tool

From a tool's detail page, **Edit** opens the metadata editor, and each version
card opens the version editor. The slug cannot be changed. Metadata changes are
applied via PATCH; editing a version's coordinates or schemas creates a new
version, pre-filled from the previous one.

### Changing Version Status

On the tool detail page, each version card has a **status dropdown**. It offers
only the transitions the platform allows from the version's current status (see
[Version Lifecycle](#version-lifecycle)) — so a `draft` can be moved to `testing`,
and a `testing` version to `active`.

### Required Fields

| Field      | Rules                                          |
|------------|------------------------------------------------|
| `name`     | 1-255 characters                               |
| `slug`     | Lowercase alphanumeric + `.`, `-`, `_`. Unique |
| `category` | One of: `docking`, `scoring`, `admet`, `ml`, `general`, `molecular-dynamics`, `quantum-chemistry`, `cheminformatics`, `bioinformatics`, `machine-learning`, `data-processing`, `other` |
| `tool_type`| One of: `container`, `pypi`, `api`.  |

---

## Creating Versions

Each tool has one or more versions. Versions are numbered monotonically
(1, 2, 3, ...) and each carries its own:

- **Docker image** (container-type) or **Package coordinates** (pypi-type)
- **Input/output/parameters schemas** (JSON Schema)
- **Resource requirements**
- **Changelog** — per-release notes (what changed in this version)
- **Test script** — runtime validation assertions
- **Git ref** — tag or commit SHA this version was built from

Tool-level metadata (description, README, tags, ownership) lives on the
tool, not the version — set it via `POST /tools` or `PATCH /tools/{id}`.

### Artifact inventory (the wheel/image must be published first)

Version creation is **hard-validated against the compute-artifacts inventory**: a
version whose
`package_name`+`package_version` (pypi) or `docker_image`+`docker_tag` (container)
is **not** recorded as an `available` artifact is rejected with **HTTP 422**. This
catches typos and not-yet-published artifacts at registration instead of at run
time.

You normally don't think about this: `build_and_register.py` records the artifact
via `POST /api/v1/compute-artifacts` right after it publishes the wheel / pushes
the image, *before* it creates the version — so the order is always satisfied. If
you register a version **by hand** (API or web), publish first and ensure the
artifact exists:

```bash
# List what's published (filter by kind/status)
GET /api/v1/compute-artifacts?kind=docker_image&status=available

# Record one (idempotent upsert on kind+name+version+registry_url)
POST /api/v1/compute-artifacts
{ "kind": "docker_image", "origin": "catalog",
  "name": "ghcr.io/example/autodock-vina", "version": "v1.2.5" }
```

The platform-admin portal exposes the same inventory as a **Compute Artifacts**
panel, and the version editor autocompletes coordinates from it and warns inline
when they aren't published.

### Via API

For **container-type** tools, provide `docker_image` and `docker_tag`:

```json
{
  "docker_image": "techneos/dataset-profiler",
  "docker_tag": "latest",
  "input_schema": { ... },
  "resource_requirements": {"cpu": "1", "memory": "2Gi"}
}
```

For **pypi-type** tools, provide `package_name`, `package_version`, and `entry_point`:

```bash
curl -X POST http://localhost:8000/api/v1/tools/{tool_id}/versions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "package_name": "molecule-property-calculator",
    "package_version": "0.1.1",
    "entry_point": "molecule_property_calculator.calculator:run",
    "input_schema": { ... },
    "output_schema": { ... },
    "parameters_schema": { ... },
    "changelog": "Add fraction-sp3 descriptor."
  }'
```

The `entry_point` format is `module.path:function` (a Python module path) — the worker imports it and calls
the resulting function with `(inputs: dict, params: dict) -> dict`.

> **Don't stamp `package_index_url`.** The install URL is environmental
> (the local devpi in dev) and is resolved at
> install time from the platform settings (`PYTHON_PACKAGE_INDEX_URL`,
> loaded via `.env`) by `core.packaging.resolve_package_index_url` —
> which both the tool-service and pipeline-service orchestrators call, so
> a tool installs from the same index whether it runs standalone or as a
> pipeline step. A `localhost` → `host.docker.internal` rewrite is applied
> so a single env value works for both host platform services and the
> Docker tool containers the worker spawns. Only set `package_index_url`
> on the tool version row if the tool genuinely ships from a different
> index (e.g. a private partner registry) —
> otherwise leave it NULL.

> **Docker image naming convention**: The pipeline orchestrator derives
> container image names as `techneos/{tool_slug}:{tag}`. If you set
> `docker_image` explicitly, it takes precedence. For tools intended for
> pipeline use, name your Docker image `techneos/{slug}` to match the
> convention (e.g., `techneos/dataset-profiler`).

### Via Web Portal

New versions are created through the **Edit** flow:

1. Navigate to the tool's detail page
2. Open the version editor from a version card
3. The fields are pre-filled from the latest version — modify as needed
4. Save — a new version is created with the next version number, as `draft`

---

## Version Lifecycle

Every tool version goes through these statuses:

```
draft → testing → active → deprecated
```

| Status       | Meaning                                           |
|--------------|---------------------------------------------------|
| `draft`      | Initial state. Not visible to pipeline builders.  |
| `testing`    | Under validation. Available for test pipelines.   |
| `active`     | Production-ready. Available for all pipelines and agents. **Triggers notification to subscribers.** |
| `deprecated` | Superseded. Existing pipelines keep working, but new ones should use a newer version. |

### Activating a Version

Registering a tool does **not** make it runnable. A new version lands as `draft`,
and submitting a run against a tool with no `active` version is rejected with
`409 Tool has no active version`.

Transitions are enforced one step at a time — `draft` cannot jump straight to
`active` — so promote it through `testing`:

```bash
# draft -> testing
curl -X PATCH http://localhost:8000/api/v1/tools/{tool_id}/versions/{version_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "testing"}'

# testing -> active
curl -X PATCH http://localhost:8000/api/v1/tools/{tool_id}/versions/{version_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

The same promotion is available from the tool's detail page in the web portal.

When a version transitions to `active`:
1. An event is published via the **EventBus** (Valkey pub/sub)
2. The **notification service** creates in-app notifications for all
   users who have subscribed/followed the tool
3. The notification appears in the bell icon in the web portal

---

## Defining Schemas

Input, output, and parameter schemas use [JSON Schema](https://json-schema.org/)
format. These schemas are used for:

- **Pipeline validation**: Ensuring tool inputs match upstream outputs
- **Agent guidance**: LLM agents use schemas to understand tool capabilities
- **Web portal display**: Rendered as documentation on the tool detail page

### Example: RDKit Input Schema

```json
{
  "type": "object",
  "properties": {
    "smiles": {
      "type": "array",
      "items": {"type": "string"},
      "description": "List of SMILES strings"
    }
  },
  "required": ["smiles"]
}
```

### Tips

- Always include `description` fields — they help both humans and LLM agents
- Use `enum` for constrained values
- Use `default` values where sensible
- Keep schemas backward-compatible across versions when possible

---

## Subscription & Notifications

### Following a Tool

Users can follow tools to receive notifications when new versions are activated.

**Via API:**
```bash
# Subscribe
curl -X POST http://localhost:8000/api/v1/subscriptions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resource_type": "tool", "resource_id": "{tool_id}"}'

# Check subscription status
curl "http://localhost:8000/api/v1/subscriptions/check?resource_type=tool&resource_id={tool_id}" \
  -H "Authorization: Bearer $TOKEN"

# Unsubscribe
curl -X DELETE http://localhost:8000/api/v1/subscriptions/{subscription_id} \
  -H "Authorization: Bearer $TOKEN"
```

**Via Web Portal:**
Click the **Follow** button on any tool's detail page.

### Viewing Notifications

- In the web portal, click the **bell icon** in the top navigation bar
- Notifications show the tool name and version number
- Click a notification to navigate to the tool detail page
- Use "Mark all read" to clear the badge

### Notification API

```bash
# List notifications
curl http://localhost:8000/api/v1/notifications \
  -H "Authorization: Bearer $TOKEN"

# Unread count (for badge)
curl http://localhost:8000/api/v1/notifications/unread-count \
  -H "Authorization: Bearer $TOKEN"

# Mark one as read
curl -X PATCH http://localhost:8000/api/v1/notifications/{id}/read \
  -H "Authorization: Bearer $TOKEN"

# Mark all as read
curl -X POST http://localhost:8000/api/v1/notifications/mark-all-read \
  -H "Authorization: Bearer $TOKEN"
```

---

## Running a Tool Directly

A registered tool can be invoked as a **tool run** — a standalone
execution of a single ToolVersion, structurally the tool-level analogue
of a `PipelineRun`. The worker treats it as a one-step Airflow DAG run,
so cancel / restart / artifact download / log proxy all work the same as
for pipelines.

### Where input data comes from

The Run UI and the API accept input data from three sources, one
control per property declared in the tool version's `input_schema`. All three modes route through MinIO, so the tool sees identical input
shape regardless of which mode supplied the data:

| Mode    | What the user supplies                          | What ends up in `parameters[<field>]` |
|---------|--------------------------------------------------|---------------------------------------|
| Dataset | Slug + version of a registered dataset          | `{type: "dataset", ref: "<slug>:vN"}` |
| Upload  | A local file (multipart-uploaded to MinIO)      | `{type: "upload", input_id, content_type, file_name}` |
| Paste   | Inline text (serialised into MinIO as a file)   | `{type: "paste", input_id, content_type, file_name}` |

#### How the tool sees its input

At dispatch time:

1. The submit handler relocates upload/paste files from the staging
   prefix `tool-run-inputs/{org_id}/{input_id}/<file>` to the canonical
   per-run prefix `tool-runs/{slug}/v{N}/{run_id}/input/<file>`.
2. The worker downloads each file into `/work/input/<field>/<file>` and
   writes `inputs.json` with `<field>_file` (the path), `<field>_source`
   (a `{type, content_type}` sidecar), and a top-level `_input_kind`
   copied from `input_schema.input_kind`.
3. `techneos_tool_runtime`'s runner pre-processes `inputs.json` before
   calling the tool's `run()`. For each `<field>_file`, it dispatches to
   the parser registered for the kind and replaces `<field>_file` with
   the canonical Python value under `<field>`.
4. The tool's `run(input_data, params)` reads `input_data[<field>]` as
   if the user had supplied it inline — same shape every time.

#### Declaring `input_kind`

Declare the tool's input contract once at the top of `input_schema`:

```json
{
  "input_schema": {
    "type": "object",
    "input_kind": "smiles_list",
    "properties": {
      "smiles": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Molecules to evaluate"
      }
    }
  }
}
```

Registered kinds live in
`techneos_tool_runtime.kinds.REGISTRY` (`packages/tool-runtime/src/techneos_tool_runtime/kinds.py` in the platform repo):

| `input_kind`         | Shape the tool receives                | Accepted formats                |
|----------------------|----------------------------------------|---------------------------------|
| `smiles_list`        | `list[{smiles, id?}]`                  | CSV, TSV, SDF, JSON, plain text |
| `protein_structure`  | `str` (absolute path under `/work/…`)  | PDB (`.pdb`/`.ent`), mmCIF (`.cif`/`.mmcif`) |

CSV/TSV parsers auto-detect SMILES and ID columns from the header (case-insensitive
match against `smiles`/`canonical_smiles`/… and `id`/`name`/`compound_id`/…).
Override explicitly via `params`: `{"smiles_column": "Canonical SMILES",
"id_column": "ChEMBL ID"}`. SDF uses the molecule's `_Name` (or a named SD tag
passed as `id_column`).

Naming convention: bare name (`protein_structure`) = singleton input,
`_list` suffix (`smiles_list`) = batch. Add a new kind in
`techneos_tool_runtime.kinds` and bump the runtime; the Pydantic validator on
`ToolVersionCreate` rejects unknown kinds at registration with the full
list of registered values.

#### Tool-supplied `parse()` override

A tool that needs something outside the registry can export `parse()`
alongside `run()`:

```python
def parse(file_path: str, params: dict) -> Any:
    """Optional. If exported, the runner calls this instead of the
    registry's default parser, then passes the return value to run()."""
    ...

def run(inputs: dict, params: dict) -> dict:
    smiles_rows = inputs["smiles"]  # whatever parse() returned
    ...
```

#### Optional standardization (SMILES_LIST)

Pass `params["standardize"]` to opt into RDKit standardization before
`run()` is called:

```json
{"standardize": {"strip_salts": true, "canonicalize": true}}
```

Dropped rows go to `inputs["_standardization_errors"]` keyed by field.
Standardization is gated by `KindSpec.supports_standardization` — it only
runs for kinds whose registry entry sets the flag, so e.g.
`protein_structure` ignores the block.

### Via Web Portal

1. Open the tool's detail page (`/tools/{id}`).
2. The **Run** panel renders one Dataset/Upload/Paste control per
   `input_schema` property, plus structured form fields for everything in
   `parameters_schema` (handling enums, booleans, numbers, strings, arrays-of-objects via a shared `SchemaForm` component).
3. Submit. The browser is redirected to `/tool-runs/{run_id}` with
   live-polled status, parameter echo, downloadable artifacts, and a
   log fetch button.
4. The `/tool-runs` hub lists every tool run visible to the caller with
   filter by status; the tool detail page also shows a "Recent runs"
   table for that specific tool.

### Via API

Inputs are **staged first**, then the staged reference is passed back on submit —
`inputs` is a list of the objects the staging endpoints return, not a list of ids.

```bash
# 1. Stage the input — upload a file...
STAGED=$(curl -s -X POST http://localhost:8000/api/v1/tool-runs/inputs \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@./mols.csv" \
  -F "parameter_name=smiles")

# ...or paste it inline
STAGED=$(curl -s -X POST http://localhost:8000/api/v1/tool-runs/inputs/paste \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"parameter_name": "smiles", "content": "CCO\nc1ccccc1",
       "content_type": "text/plain", "filename": "smiles.txt",
       "tool_slug": "molecule-property-calculator", "tool_version": "1"}')

# 2. Submit, passing the staged object back in `inputs`
curl -X POST http://localhost:8000/api/v1/tool-runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"tool_id\": \"$TOOL_ID\",
    \"parameters\": {\"detailed\": true},
    \"inputs\": [$STAGED]
  }"
```

`POST /tools/{tool_id}/runs` is a convenience alias that takes the same
body. Either route accepts `version_id` to pin a specific tool version
instead of the latest active one. `GET /tool-runs/{id}` auto-syncs from
Airflow when the run is not yet terminal.

### Run storage layout

Every byte of a tool run lives under a single MinIO prefix:

```
tool-runs/{slug}/v{N}/{run_id}/input/<file>     ← uploaded/pasted/dataset inputs
tool-runs/{slug}/v{N}/{run_id}/output/<file>    ← worker-uploaded artifacts
```

Staged-but-unbound inputs (uploaded then never submitted) sit at
`tool-run-inputs/{org_id}/{input_id}/<file>` until they're either
relocated by submit or cleaned up by `DELETE /tool-runs/inputs/{id}`.
Pipeline-run outputs use the parallel
`pipeline-runs/{pipeline_slug}/v{N}/{run_id}/{step_name}/<file>` layout.
The orchestrators compose the prefix and thread it into the Airflow
conf as `step.key_prefix`.

---

## Tool Execution Model

### The execution contract

Every tool run — whichever way it was triggered — goes through a single
execution contract. The worker stages a `/work/` host directory, writes `/work/inputs.json` +
`/work/params.json`, bind-mounts the whole dir into the container, and the
image's runner calls your `run(inputs, params)`:

| Tool type | Image | Entry point |
|---|---|---|
| `container` | `techneos/{tool_slug}:{tag}` (or explicit `image`) | Image's `ENTRYPOINT` — typically `python -m techneos_tool_runtime.runner` inherited from `techneos/tool-runtime` |
| `pypi` | `techneos/tool-runtime:latest` | Worker pip-installs the package + runtime, then invokes the runner |

The runner reads `/work/inputs.json` + `/work/params.json` (which the
worker writes before launching the container), imports `ENTRYPOINT_SPEC`
(set by the image / by the worker for pypi), and calls
`run(inputs: dict, params: dict) -> dict`. Side-effect files written to
`/work/output/` are collected as artifacts (read back from the host work dir
directly — no `docker cp`).

#### Building a container tool image

Container images inherit from `techneos/tool-runtime` and install any extra system
libs they need in their own Dockerfile. The base provides
`python -m techneos_tool_runtime.runner` as
its `ENTRYPOINT`; the tool's Dockerfile installs the tool package and
sets `ENTRYPOINT_SPEC`:

```dockerfile
ARG BASE_REGISTRY=
ARG BASE_TAG=latest
FROM ${BASE_REGISTRY}techneos/tool-runtime:${BASE_TAG}

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV ENTRYPOINT_SPEC=dataset_profiler.core:run
```

The `run` function inside `src/dataset_profiler/core.py` is the only
custom code:

```python
def run(inputs: dict, params: dict) -> dict:
    # inputs["dataset_file"] is the staged input file, resolved by the worker
    # from the run's inputs and declared via `input_kind`.
    import pandas as pd
    df = pd.read_csv(inputs["dataset_file"])
    # Side-effect artifacts go through the runtime helpers:
    from techneos_tool_runtime import write_artifact
    write_artifact("report.html", render_report(df, params))
    return {"n_rows": len(df), "report_file": "report.html"}
```

Build the shared runtime image first, then the tool image:

```bash
# the shared base image is built from the platform repo:
#   python setup/wheels/publish_tool_runtime.py --skip-register
docker build -t techneos/dataset-profiler:latest tools/dataset-profiler/
```

> **Tip:** With the Docker backend, the image must be available on the Docker
> daemon that the Airflow worker connects to — which is why a local build is
> enough for local runs. The `techneos/tool-runtime` base image is built by the
> platform; container tool images are built by their own `build_and_register.py`.

For **pypi tools**, no Dockerfile is needed. The worker pip-installs the
package into `techneos/tool-runtime` at dispatch time and invokes the runner
— the package must be published to the configured package index (the local devpi).

#### Common failure: `ImageNotFound`

If you see an error like:

```
docker.errors.ImageNotFound: No such image: techneos/dataset-profiler:latest
```

It means the Docker image was never built or is not accessible to the
worker's Docker daemon. Build and tag the image as shown above.

---

## Using Tools in Agents

Agents reference tools by slug in their `tools` list:

```json
{
  "name": "ChemAssistant",
  "type": "conversational",
  "framework": "pydantic-ai",
  "tools": ["calculate_molecule_properties"],
  "system_prompt": "You are a cheminformatics assistant...",
  "model_config": {
    "provider": "<provider-slug>",
    "model": "gemini-2.0-flash"
  }
}
```

The agent framework uses the tool's input/output/parameters schemas to
generate function-calling definitions, enabling the LLM to invoke tools
with proper arguments.

### Contributing a tool function to an agent

A pypi tool can expose an async function to the platform's built-in assistant by
declaring it in the `techneos.platform_assistant_tools` entry-point group — the
agent-service pip-installs the wheel and discovers the entry point at startup. The
[Molecule Property Calculator](#molecule-property-calculator-example--pypi-tool-with-agent-surface)
does exactly this with `calculate_molecule_properties`, so one package serves both
as a pipeline/tool-run step and as an agent capability.

For building agents themselves, see the [Agent Building Guide](agent-guide.md).

---

## Web Portal Walkthrough

### Tool Registry List (`/tools`)

- **Search**: Type to filter tools by name or description
- **Category filters**: Click category pills to filter (all, docking, scoring, admet, ml, general)
- **Type badge**: Each tool shows its type (Container, Pypi, API) as a colored badge
- **Register Tool**: Button in the top-right corner to create a new tool
- **Click** a tool name to view its detail page

### Tool Detail Page (`/tools/{id}`)

The detail page shows:

1. **Header**: Name, description, category badge, type badge, tags, public/private
2. **Action buttons**:
   - **Edit**: Edit metadata, or edit a version (pre-filled from the latest)
   - **Follow**: Subscribe/unsubscribe from version notifications
3. **Quick Start**: For the active version — shows install command (pip/conda) or Docker pull command
4. **Pipeline/Agent usage**: Shows the tool's slug and links to use it in pipeline or agent builders
5. **Version history**: Expandable cards for each version showing:
   - **Status dropdown** — offers only the transitions allowed from the current status
   - Installation instructions
   - Docker image reference (for container tools)
   - Package coordinates (for pypi tools)
   - Resource requirements
   - Changelog (per-release notes, Markdown-rendered)
   - Test script
   - Git reference
   - Input/output/parameters schemas (collapsible)

### Create/Edit Tool Page (`/tools/new`)

The form supports two modes depending on query parameters:

| Mode      | URL                      | Behavior                                      |
|-----------|--------------------------|-----------------------------------------------|
| Create    | `/tools/new`             | Empty form, all fields editable               |
| Edit      | `/tools/new?edit={id}`   | Pre-filled, slug read-only, creates new version |

The form adapts based on tool type:
- **Container**: Shows Docker image and tag fields
- **Pypi**: Shows package name, version, entry point, and optional package index URL fields
- **API**: Shows only the common fields (schemas, resources, etc.)

When editing an existing tool, all version fields are pre-filled from the
latest version, so you only need to change what's different.

---

## Molecule Property Calculator Example — Pypi Tool with Agent Surface

This section walks through the **Molecule Property Calculator** (MPC) —
an RDKit-powered tool that computes molecular descriptors from SMILES
strings. It's a `pypi` tool (worker pip-installs it at dispatch) and
*also* exposes an async function used directly by the Platform Assistant
agent. For the basic pypi mechanics (build + publish + register), see
the [Structure Alerts Example](#structure-alerts-example--pypi-tool) below; this
section focuses on what's unique to MPC: the dual delivery surface.

### Package Structure

The tool lives under `tools/molecule-property-calculator/` as a
**standalone** Python package — not part of any workspace, so
its heterogeneous deps (rdkit, etc.) don't have to resolve against every
other tool in the repo:

```
tools/molecule-property-calculator/
├── pyproject.toml                       # standalone uv project + its own uv.lock
├── build_and_register.py                # builds wheel, publishes to DevPI, registers
├── tool_def.json                        # single source of truth: schemas + agent_tools + resource_requirements
├── README.md                            # tool documentation → tools.readme
└── src/molecule_property_calculator/
    ├── __init__.py
    ├── calculator.py                    # run(inputs, params) -> dict — pypi entry point
    └── platform_plugin_tools.py         # async calculate_molecule_properties + PLATFORM_PLUGIN_TOOLS list
```

This package also contributes the ``calculate_molecule_properties`` async
function to the built-in Platform Assistant agent via the
``techneos.platform_assistant_tools`` entry-point group (declared in
``pyproject.toml``). At agent-service startup, the service reads the
tool's ``agent_tools`` column from ``PypiConfig``, pip-installs the
published wheel from the configured package index, and discovers the
entry point — no Dockerfile baking required.

### Core Library (`calculator.py`)

The library exposes a single entry point:

```python
from molecule_property_calculator.calculator import run

result = run(
    {"smiles": ["CCO", "c1ccccc1"]},
    {"detailed": True},
)
# → {"results": [...], "errors": [], "count": 2, "params_used": {"detailed": True}}
```

Each entry in `smiles` can be a plain SMILES string or an object with an
optional `id` field for tracking:

```python
result = run({"smiles": [
    {"smiles": "CCO", "id": "ethanol"},
    {"smiles": "c1ccccc1", "id": "benzene"},
]})
```

Properties computed: MW, LogP, HBD, HBA, TPSA, rotatable bonds, heavy atom
count, aromatic/aliphatic rings, fraction sp3, ring count, heteroatoms,
canonical SMILES, and molecular formula.

### Agent Tool Function (`platform_plugin_tools.py`)

The same computation is exposed as an async function for LLM agents:

```python
from molecule_property_calculator.platform_plugin_tools import calculate_molecule_properties

result = await calculate_molecule_properties(
    smiles=["CCO", "c1ccccc1"],
    detailed=True,
)
```

This function is registered with the `ToolRegistry` as part of `PLATFORM_TOOLS`
and is available to any agent that uses platform tools. Agents can call it
directly during LLM reasoning — no pipeline or Docker container needed.

### Register via `build_and_register.py`

```bash
# With the platform dev stack running, register the tool:
bin/register.sh tools/molecule-property-calculator

# Or with explicit credentials
bin/register.sh tools/molecule-property-calculator --email admin@example.com

# Re-create if already exists
bin/register.sh tools/molecule-property-calculator --upsert
```

The script:

1. **Builds + publishes** the wheel (`uv build`, then publishes it to the
   configured package index — the local devpi).
2. **Authenticates** via a cached token (`~/.techneos/{env}_token.json`) or interactive login
3. **Registers** the tool as `tool_type: pypi` with category `general`,
   sending the contents of `README.md` as the tool-level `readme` field
4. **Creates a version** with:
   - `package_name`, `package_version`, `entry_point` (`molecule_property_calculator.calculator:run`)
   - `agent_tools: ["calculate_molecule_properties"]` — signals the
     agent-service to install this package at startup and discover its
     `techneos.platform_assistant_tools` entry point
   - JSON Schemas for input, output, and parameters
   - `resource_requirements` (0.5 CPU, 512Mi memory)
   - `changelog` is left empty by default — populate via the web UI or
     `PATCH /tools/{id}/versions/{id}` after release notes are written
5. **Subscribes** the current user to tool notifications
6. **Activates** the version (triggers events + notifications)

### How Agents Discover and Invoke It

There are two pathways for agents:

**1. List + describe (all agents):** Any agent with `list_tools` and
`get_tool_info` can discover the tool, read its schemas, and tell the user
about it. These are built-in platform tools.

**2. Inline execution (agents with platform tools):** The
`calculate_molecule_properties` function is wired into `PLATFORM_TOOLS`. When
an agent's LLM decides the user's request needs property calculation, it calls
this function directly — results are returned in the SSE stream as tool
results.

The tool also appears in the pipeline builder for use in automated workflows.

### Verify in Web Portal

1. Open http://localhost:3000/tools
2. Find "Molecule Property Calculator" — note the **Pypi** type badge
3. Click to open the detail page; the tool's README renders in the header
4. Expand the version to see schemas, package coordinates, changelog, and test script
5. Click the bell icon — you should see a notification about the activation

---

## Dataset Profiler Example — Container Tool

This section walks through the Dataset Profiler as an example of a
**container-type** tool that runs standalone or in pipelines.

### What It Does

The Dataset Profiler summarises any tabular dataset (CSV, TSV, or JSON) into an
**HTML or PDF report**. It concatenates the input tables, identifies numeric
columns, renders per-column distribution histograms (or a sample × metric
heatmap), and emits a Jinja-templated report — PDF rendering via WeasyPrint. It
works on a single uploaded file or on upstream pipeline artifacts. Key
parameters:

| Parameter       | Description                                              |
|-----------------|---------------------------------------------------------|
| `format`        | Output format: `pdf` (default) or `html`                |
| `include_plots` | Render per-column histograms and embed them (default true) |
| `title`         | Report title shown on the cover page                    |
| `input_format`  | Force a reader (`auto`/`csv`/`tsv`/`json`); `auto` infers from extension |

### Container Contract

The Dataset Profiler uses the unified runtime contract — same shape
as every other refactored tool:

- **Inputs**: The worker writes `/work/inputs.json` with resolved file
  paths (e.g. `{"dataset_file": "/work/input/data.csv"}`). Dataset
  parameters (`dataset`, `dataset_id`, or anything ending in
  `_dataset` / `_dataset_id`) are resolved by the platform; the file is
  downloaded into `/work/input/`. Upstream-step artifacts land under
  `/work/input/upstream/{step_name}/`.
- **Parameters**: The worker writes `/work/params.json` with the step's
  parameters dict verbatim.
- **Entry**: The image's `ENTRYPOINT` (`python -m techneos_tool_runtime.runner`)
  reads both files and calls `dataset_profiler.core:run(inputs, params)`.
- **Output**: The function returns a dict (`report_file`, `n_rows`,
  `numeric_columns`, `plots`) — written to `/work/output/result.json`.
  Side-effect artifacts (`report.{pdf,html}`, `plot_*.png`) go through
  `techneos_tool_runtime.write_artifact()`, which puts them under
  `/work/output/`. The worker collects everything from there.
- **Image naming**: The orchestrator derives image names as
  `techneos/{tool_slug}:{tag}`. Name your image accordingly or set
  `docker_image` explicitly on the tool version.

### Build the Docker Image

The Dataset Profiler builds on `techneos/tool-runtime` and installs WeasyPrint's
libpango/libcairo libs in its own Dockerfile so it can render PDFs:

```bash
# the shared base image is built from the platform repo:
#   python setup/wheels/publish_tool_runtime.py --skip-register
docker build -t techneos/dataset-profiler:latest tools/dataset-profiler/
```

### Test Locally

The container takes the same shape the worker hands it — a `/work/` bind
mount with `inputs.json` + `params.json`:

```bash
WORK=$(mktemp -d) && mkdir -p "$WORK/input" "$WORK/output"

# Profile a dataset file mounted under /work/input/
cp ./my_data/measurements.csv "$WORK/input/data.csv"
echo '{"dataset_file": "/work/input/data.csv"}' > "$WORK/inputs.json"
echo '{"format": "html", "include_plots": true, "title": "Sample QC Summary"}' > "$WORK/params.json"
docker run --rm -v "$WORK:/work" techneos/dataset-profiler:latest

# Check results
cat "$WORK/output/result.json"
ls "$WORK/output/"          # report.html (or report.pdf) + plot_*.png
```

> **Note**: When the worker runs this in a pipeline, it sets up `/work/`
> from the step config — resolving `dataset` parameters (e.g.
> `zinc20-druglike:v1`) to actual paths under `/work/input/`, or injecting
> upstream step artifacts. The local commands above just simulate what the
> worker would have written.

### Register via the tool's `build_and_register.py`

Each self-contained tool ships its own `build_and_register.py` at
`tools/{slug}/build_and_register.py`; `bin/register.sh` runs it for you:

```bash
# Build the image + register a draft version
bin/register.sh tools/dataset-profiler

# Rebuild and replace an existing registration
bin/register.sh tools/dataset-profiler --upsert
```

The new version lands as `draft` — promote it through `testing` to `active`
before it can be run (see [Version Lifecycle](#version-lifecycle)).

The register script:
1. Builds the Docker image `techneos/dataset-profiler:{pyproject_version}` (and
   tags `:latest`) — skip with `--skip-build` if you already built it
2. Registers the tool with `tool_type: container`, `category: data-processing`
3. Creates a new version; the worker runs every container tool through the
   unified `/work/` mount + techneos-tool-runtime path

### Register via Web Portal

1. Go to **Tools** → **Register Tool**
2. Set name to "Dataset Profiler", type to `container`, category to `data-processing`
3. In the version section, set Docker image to `techneos/dataset-profiler`, tag to `latest`
4. Paste the input/output/parameters schemas from `tools/dataset-profiler/`
5. Click **Register Tool**. The version is created as `draft` — promote it through `testing` to `active` before it can run

### Writing Your Own Container Tool

To create a new container tool, follow this pattern (mirror what
`tools/dataset-profiler/` does):

1. **Create a directory** under `tools/` (e.g., `tools/my-tool/`)
2. **Write a Python package** with `src/my_tool/core.py` exposing
   `def run(inputs: dict, params: dict) -> dict` — the runtime handles
   I/O via `/work/inputs.json` + `/work/params.json` so you never touch
   env vars or filesystem paths directly.
3. **Add a `pyproject.toml`** that depends on `techneos-tool-runtime>=0.1,<1`,
   resolved from the package index (the local devpi) like any other dependency.
4. **Write a Dockerfile** on top of `techneos/tool-runtime` — see below.
5. **Build** the shared `techneos/tool-runtime` image first, then the tool image.
6. **Test locally** with a hand-crafted `/work/` bind mount.
7. **Add `build_and_register.py`** — constants + a single
   `management.catalog` (`packages/management/src/management/catalog.py` in the platform repo) call:
   `register_pypi_tool` for pypi tools, `register_container_tool` for container
   tools (it builds/pushes the image, records the artifact, and upserts the Tool +
   ToolVersion). Mirror an existing
   `tools/<slug>/build_and_register.py`.

```dockerfile
ARG BASE_REGISTRY=
ARG BASE_TAG=latest
FROM ${BASE_REGISTRY}techneos/tool-runtime:${BASE_TAG}

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

ENV ENTRYPOINT_SPEC=my_tool.core:run
```

---

## Structure Alerts Example — Pypi Tool

Pypi tools are pip-installable Python packages published to a package index
(the local devpi in dev). The worker
installs the package at dispatch time and invokes the entry point function.
(Unlike the Molecule Property Calculator above, Structure Alerts is a *plain*
pypi tool — no agent surface — so it shows the minimal pypi shape.)

### Package Structure

The tool lives under `tools/structure-alerts/` as a **standalone** Python
package — not part of any workspace, so it can ship its own `uv.lock`
without dragging other tools' resolution:

```
tools/structure-alerts/
├── pyproject.toml             # [tool.techneos] delivery=pypi, entry_point=...:run
├── build_and_register.py      # Registration script (idempotent)
├── README.md
├── tool_def.json              # name/slug + input/output/parameters schemas
├── examples/                  # input.json, params.json
├── tests/
│   └── test_checker.py
└── src/structure_alerts/
    ├── __init__.py
    └── checker.py             # run(input_data, params) -> dict
```

### 1. Register the tool

```bash
# With the platform dev stack running, build and register (prompts for login):
bin/register.sh tools/structure-alerts

# Or recreate an existing tool (deletes + re-registers)
bin/register.sh tools/structure-alerts --upsert
```

The registration script:
1. Builds the package: `uv build --out-dir dist`
2. Publishes to the package index (DevPI/pypiserver)
3. Registers the tool with `tool_type: pypi`
4. Creates a version with package name, version, and entry point

### 2. Entry Point Contract

Every pypi tool exposes a `run(input_data, params)` function:

```python
def run(input_data: dict | list, params: dict) -> dict:
    """Process the inputs according to the given parameters."""
    ...
    return {"results": ..., "count": ...}
```

- `input_data`: the parsed input — for `smiles_list` tools, the list of
  `{smiles, id}` compounds (delivered under the key the platform injects via
  `smiles_list_key`)
- `params`: the run parameters, validated against `parameters_schema`
- Returns: a JSON-serializable dict

### 3. Activate and Run

A newly registered version lands as `draft`. Promote it through `testing` to
`active` (see [Version Lifecycle](#version-lifecycle)) — a run against a tool with
no active version is rejected with `409`. Then run it from the portal or the API
(see [Running a Tool Directly](#running-a-tool-directly)).

At dispatch the platform resolves the slug to its active version, launches the
`techneos/tool-runtime` image, pip-installs the declared package, and calls the
entry point with the staged inputs and validated parameters.

---

## Best Practices

### Docker Images (for container tools)

- Always build and tag images as `techneos/{slug}:{version}` to match the naming convention
- Inherit from `techneos/tool-runtime` so the generic
  runner handles I/O — your image only needs its extra system deps (if any),
  `pip install .`, and `ENV ENTRYPOINT_SPEC=...`
- Keep images small — use slim base images and multi-stage builds
- Tool code writes to `/work/output/` via `techneos_tool_runtime.write_artifact()`,
  not directly to filesystem paths
- Log to stdout/stderr — the worker captures container logs for debugging
- Test images locally by hand-crafting `inputs.json` + `params.json` in a
  tmp dir and bind-mounting it as `/work` (see ADMET Predictor example)

### Naming & Slugs

- Use clear, recognizable names (e.g., "Structure Alerts" not "sa-tool-v2")
- Slugs should be lowercase, hyphenated (e.g., `autodock-vina`, `structure-alerts`)
- Slugs are permanent — choose carefully

### Versioning

- Bump versions for any change to schemas, dependencies, or Docker image
- Use the per-version `changelog` field to document what changed in each
  release; the tool-level `readme` is for what the tool *does* overall
- Keep test scripts up to date with each version
- Deprecate old versions explicitly — don't just create new ones

### Schemas

- Be specific in descriptions — these are used by LLM agents
- Include `default` values for optional parameters
- Use `required` arrays to specify mandatory fields
- Test schemas against real data before activating a version

### Notifications

- Encourage team members to follow tools they depend on
- Write meaningful README docs
- Use the `testing` status for internal validation before activating

### Categories

| Category               | When to use                                      |
|------------------------|--------------------------------------------------|
| `docking`              | Molecular docking tools (AutoDock, Glide, etc.)  |
| `scoring`              | Scoring functions, binding affinity prediction   |
| `admet`                | ADMET property prediction                        |
| `ml`                   | Machine learning models and training tools       |
| `general`              | Everything else (cheminformatics, utilities)     |
| `molecular-dynamics`   | MD simulation tools                              |
| `quantum-chemistry`    | QM/MM, DFT, ab initio tools                      |
| `cheminformatics`      | Chemical informatics, fingerprinting             |
| `bioinformatics`       | Sequence analysis, genomics, proteomics          |
| `machine-learning`     | ML/AI model training and inference               |
| `data-processing`      | Data transformation, filtering, aggregation      |
| `other`                | Catch-all for uncategorized tools                |

### Pypi Tools

- Store tool packages under `tools/{name}/` as **standalone** uv projects (not workspace members) — heterogeneous tool deps don't fight for a single resolution
- Expose a single `run(inputs: dict, params: dict) -> dict` entry point
- Use `uv build --out-dir dist` to build the wheel
- Publish the wheel to the configured package index (the local devpi)
- Include a `register.py` with `--force-new-version` for idempotent re-registration
- Write unit tests under `tests/` and integration tests in `register.py`
- Mark the tool type as `pypi` for script-based tools — 

### Container Tools

- Name Docker images as `techneos/{tool_slug}` to match the orchestrator convention
- Build on `techneos/tool-runtime*` and let the inherited runner invoke your
  `run(inputs, params)` — read inputs/params from `/work` via techneos-tool-runtime,
  not from env vars
- Write side-effect artifacts to `/work/output/` — this is where the backend
  collects them (use `techneos_tool_runtime.artifact_path` rather than hardcoding)
- Use `python:3.12-slim` or similar minimal base images to reduce build time
- Test locally with a hand-crafted `/work` bind mount before registering —
  verify exit code 0 and `/work/output/` contents
- Log to stderr/stdout — the backend captures container logs for debugging
- Keep containers stateless — all input arrives under the `/work` mount

---

## See Also

- [Dataset Registration Guide](dataset-guide.md) — Registering and versioning datasets (ZINC20 example)
- [Agent Building Guide](agent-guide.md) — Building and deploying AI agents
- [App Registration Guide](app-guide.md) — Building and deploying embedded apps
- [Task Guide](task-guide.md) — Authoring and registering human tasks (offline work for a person or team)
