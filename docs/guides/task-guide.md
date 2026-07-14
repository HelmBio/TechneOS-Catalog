# Task Guide

How to author, register, and remove a **human task** — a unit of offline work
(synthesis request, biological assay, compound review, …) that a person or team
completes through the platform's Task Run UI. It uses the catalog's **Synthesis
Request** and **Biological Assay** as worked examples.

A human task is the simplest catalog type to register: it is a `tool_type="human"`
Tool + ToolVersion with **no artifact** — there is no wheel or container image to
build, publish, or record. Registration is purely an API call driven by a
`task_def.json`, the same shape as `datasets/`.

---

## Table of Contents

1. [Task Layout](#task-layout)
2. [The task_def.json](#the-task_defjson)
3. [Assignment](#assignment)
4. [Lifecycle Overview](#lifecycle-overview)
5. [Synthesis Request — Walkthrough](#synthesis-request--walkthrough)
6. [Registering a Task](#registering-a-task)
7. [Running a Task](#running-a-task)
8. [Removal](#removal)
9. [Versioning](#versioning)
10. [Adding a New Task](#adding-a-new-task)
11. [See Also](#see-also)

---

## Task Layout

Each task is a self-contained directory under `tasks/`. It is **not** a Python
package — there is nothing to build — so it has no `pyproject.toml`:

```
tasks/
└── synthesis-request/
    ├── task_def.json     # the full task definition (schemas + human_config)
    ├── register.py       # reads task_def.json, calls management.catalog.register_task
    ├── README.md         # surfaced as the task's readme in the portal
    └── examples/         # sample input/output files
```

Register it from the repo root:

```bash
bin/register.sh tasks/synthesis-request
```

Because a task directory has no `pyproject.toml`, `bin/register.sh` runs it from
the repo root with the `tooling` dependency group — the group that provides
`techneos-management`. Nothing else is installed, because nothing else is needed.

---

## The task_def.json

The definition carries the task's identity, its input/output/parameter JSON
schemas, and the human-assignment config:

| Field | Purpose |
| --- | --- |
| `name` / `slug` / `description` | Identity and catalog display. `slug` is the stable key used for upsert and removal. |
| `tool_type` | Always `"human"` for a task. |
| `category` / `tags` / `is_public` | Catalog metadata. |
| `input_schema` | JSON Schema for the data the assignee receives (e.g. the compounds to synthesize). |
| `output_schema` | JSON Schema for the deliverable they submit (e.g. per-compound certificate-of-analysis details). |
| `parameters_schema` | JSON Schema for the run parameters shown in the submit wizard (e.g. file formats, project details). |
| `human_config` | How the task is assigned and tracked — see [Assignment](#assignment). |

Schemas are ordinary JSON Schema (`$schema: https://json-schema.org/draft/2020-12/schema`)
and are validated by the platform on submit, so an assignee cannot finish a run
with a deliverable that doesn't match `output_schema`.

---

## Assignment

```json
"human_config": {
  "assignment_type": "team",
  "due_in_hours": 168,
  "require_attachments": true,
  "priority": "medium"
}
```

| Key | Meaning |
| --- | --- |
| `assignment_type` | `"team"` (assign to a team) or `"user"` (assign to one person). |
| `due_in_hours` | Default due-date offset from assignment. |
| `require_attachments` | Whether finishing the run requires file attachments. |
| `priority` | Default priority shown in the work queue. |

`human_config` also accepts `default_team_slug` / `default_user_email` — a standing
assignee applied to every run that doesn't name one. **The catalog's tasks
deliberately omit it**, because a team slug or an email is a property of the
*deployment*, not of the task: a slug that means something in one organization
means nothing in another. The platform stores these as plain strings and does not
verify that the team or user exists, so a stale default silently routes runs into a
queue nobody watches.

With no default, the platform requires an explicit assignee and rejects a run that
omits one:

```
400  Tool 'synthesis-request' has no default assignee;
     supply assigned_user_id or assigned_team_slug
```

Set a default only if the task is genuinely owned by one standing team in your
deployment, and only with a slug you have confirmed exists.

---

## Lifecycle Overview

1. **Author** `task_def.json` (plus `README.md` and `examples/`).
2. **Register** with `bin/register.sh` → upserts a `tool_type="human"` Tool and
   creates a ToolVersion carrying the schemas and assignment config. No build step.
3. **Run** from the portal or `POST /api/v1/task-runs/from-tool`: the run is assigned, the
   assignee works it through the action log (start / accept / update / delegate /
   escalate / decline / finish / cancel), exchanges threaded follow-up messages,
   and submits output artifacts (staged in MinIO, validated against
   `output_schema` on submit).
4. **Revise** by editing `task_def.json` and re-registering (see
   [Versioning](#versioning)).
5. **Remove** with `bin/task_removal.sh` — runs, submitted files, versions, task.

Unlike a computational tool, a task has no `draft → testing → active` version
gate — there is no artifact to validate, so a registered task is runnable
immediately.

---

## Synthesis Request — Walkthrough

`tasks/synthesis-request/` is the worked example: request synthesis of target
compounds (SDF or CSV in), receive a certificate of analysis per compound —
identity, purity, analytical data (out).

### Step 1: Register

```bash
bin/register.sh tasks/synthesis-request
```

This upserts the `synthesis-request` human Tool and creates a version. The script
prints the Tool id, the API URL, and the portal URL.

### Step 2: Verify

Open the portal, go to **Tasks**, and confirm **Synthesis Request** appears with
its input and output sections rendered from the schemas.

### Step 3: Submit a run

Start a run from the portal, assigning it to a team that exists in your
deployment — the task ships no default assignee (see [Assignment](#assignment)).
`tasks/synthesis-request/examples/input.sdf` is a two-molecule file you can hand
it. Working the run through to **finish** exercises the whole path: assignment, the
action log, follow-up messages, and artifact submission with `output_schema`
validation.

---

## Registering a Task

`register.py` is configuration plus a couple of calls — it reads `task_def.json`
and calls `management.catalog.register_task`:

```bash
# Register (returns the existing task untouched if it's already there)
bin/register.sh tasks/synthesis-request

# Recreate: DELETE then re-create
bin/register.sh tasks/synthesis-request --upsert
```

Registration talks only to the gateway REST API. A task has no artifact, so —
unlike a tool or an app — nothing is built, published, or recorded in the
compute-artifacts inventory. Auth uses the cached `~/.techneos` token, or prompts;
pass `--email` / `--password` for a non-interactive run.

### Idempotency

`register_task` looks up the task by slug (`?tool_type=human`), so re-registration
is safe: without `--upsert` it returns the existing Tool untouched; with `--upsert`
it deletes and recreates it. Note that `--upsert` takes the task's run history down
with the Tool — prefer a new version when runs matter.

---

## Running a Task

Runs are normally driven from the portal, but the API underneath it is the same.
Creating a run needs the task's **version id**, so look the task up first:

```bash
TOKEN=$(jq -r .access_token ~/.techneos/development_token.json)
API=http://localhost:8000/api/v1

# /tools is paginated — the rows are under .items
TOOL_ID=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/tools?tool_type=human" \
  | jq -r '.items[] | select(.slug=="synthesis-request") | .id')
VERSION_ID=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/tools/$TOOL_ID" \
  | jq -r '.versions[-1].id')

curl -X POST "$API/task-runs/from-tool" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"tool_slug\": \"synthesis-request\",
    \"tool_version_id\": \"$VERSION_ID\",
    \"assigned_team_slug\": \"<a-team-in-your-deployment>\",
    \"input_snapshot\": {\"compounds\": [{\"id\": \"CPD-1\", \"smiles\": \"CC(=O)Oc1ccccc1C(=O)O\"}]},
    \"due_in_hours\": 168
  }"
```

`/task-runs/from-tool` is the user-facing entry point — it takes a task by slug and
assigns it. (Plain `POST /task-runs` also exists, but it is the internal payload the
worker uses; it expects a resolved org and pre-snapshotted input.) `input_snapshot`
is the data the assignee sees, validated against `input_schema`; to attach staged
files, pass their ids in `input_ids`.

The assignee then advances the run through its action log and finishes it via
`POST /task-runs/{id}/submit`, whose `output_data` is validated against
`output_schema`.

---

## Removal

Use `bin/task_removal.sh` — it is the task-aware path, and it cleans up the run
history and the submitted files that a plain tool removal would leave behind:

```bash
# Preview first — always
bin/task_removal.sh synthesis-request --dry-run

# Remove the task: all runs (+ their MinIO files), all versions, then the task
bin/task_removal.sh synthesis-request

# Scoped to one version: that version's runs and the version itself.
# The task and its other versions survive.
bin/task_removal.sh synthesis-request v2
```

A run that is still open counts as **active**, and removal stops to confirm before
cancelling it. Pass `--force` to cancel active runs without prompting — worth
being deliberate about, since those are runs a person may be part-way through.

The `--dry-run` output is worth reading rather than skimming: it names every run,
every MinIO file, every version, and the task, so you can see the full blast radius
before committing to it.

---

## Versioning

A task is a Tool with versions. To publish revised schemas or assignment config as
a *new* version while keeping run history, edit `task_def.json` and re-register
against the existing Tool — a new ToolVersion is appended. Existing runs keep
pointing at the version they were submitted against, so an in-flight run is never
reshaped underneath its assignee.

Use `--upsert` only when you want a clean slate: it deletes the Tool, and the runs
go with it.

---

## Adding a New Task

1. Copy an existing task as the starting point:
   ```bash
   cp -r tasks/synthesis-request tasks/my-task
   ```
2. Edit `tasks/my-task/task_def.json`:
   - set `name`, `slug` (stable, kebab-case), `description`, `category`, `tags`;
   - define `input_schema` (what the assignee receives) and `output_schema`
     (the deliverable they submit);
   - define `parameters_schema` for the submit-wizard fields;
   - set `human_config` (assignment mode, due window, attachments, priority).
3. `register.py` reads `slug` from `task_def.json`, so usually only its module
   docstring needs updating.
4. Add a `README.md` (surfaced as the task's readme) and `examples/`.
5. Register:
   ```bash
   bin/register.sh tasks/my-task
   ```

The most consequential decision is `output_schema`. It is the contract the platform
enforces on submit, and it is what makes a completed task machine-readable rather
than a note in a comment thread — so model the deliverable, not the conversation.

---

## See Also

- [Dataset Registration Guide](dataset-guide.md) — Registering and versioning datasets (ZINC20 example)
- [Tool Registration Guide](tool-guide.md) — Registering computational tools (pypi and container)
- [Agent Building Guide](agent-guide.md) — Building and deploying AI agents
- [App Registration Guide](app-guide.md) — Building, registering, and deploying embedded apps
