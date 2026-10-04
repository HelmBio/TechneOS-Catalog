# techneos-catalog

The **registered content** for the TechneOS platform — the user-facing
artifacts the platform serves through its catalog: datasets you can query, tools
you can run, pipelines (DAGs of tools) you can execute, apps you can launch,
agents you can chat with, and human tasks you can assign to a person or team.

```
.
├── datasets/    # registered datasets (data + metadata + registration script)
├── tools/       # registered tools (pypi or container, with build + register scripts)
├── pipelines/   # registered pipelines (DAGs of tools: pipeline_def.json + register script)
├── apps/        # registered embedded apps (Docker images launched in the UI)
├── agents/      # registered LLM agents (wheel packages + registration script)
└── tasks/       # registered human tasks (offline work for a person/team: task_def.json + register script)
```

The platform infrastructure — services, gateway, CLI, web shell, worker, and core
libraries — lives in the separate **platform repo** (`techneos`). This repo holds only what
users see, clone, and extend; it talks to a running platform purely over its
REST API plus the shared package index.

## The duality

Every catalog entry serves two purposes at once, by design:

1. **First-party content the platform ships.** Real, registered entries seeded
   into a fresh install — load-bearing, not throwaway samples.
2. **Reference implementations.** Each entry is also the worked example for
   adding your own: clone-and-edit. To add an entry of a given type, copy an
   existing one of that type and change the definition.

Don't delete them; copy them.

## How this repo relates to the platform

Catalog packages reach the platform in two ways, both index/API based — there is
**no source dependency** on the platform monorepo:

| Coupling | Surface | Provided by |
| --- | --- | --- |
| Build/register | `management.catalog` / `management.registration` (imported by the `*register*.py` scripts) | `techneos-management` wheel from the package index (per-package `[dependency-groups] publish`; an ephemeral `--with techneos-management` env for scripts without a pyproject) |
| Tool runtime | `techneos_tool_runtime` (`artifact_path`, `write_artifact`, parsers) | `techneos-tool-runtime` wheel from the package index — the runtime library packaged tools build against |
| API | `POST /api/v1/{datasets,tools,pipelines,apps,agents,compute-artifacts}` | the running gateway, selected by `--env` |

### Package index

The wheels the register scripts import (`techneos-management`, plus
`techneos-tool-runtime` once tools arrive) come from a package index proxied
through the gateway at `{PLATFORM_API_URL}/simple/`. The `bin/register.sh`
script derives `UV_DEFAULT_INDEX` and `UV_PUBLISH_URL` from `PLATFORM_API_URL`
before invoking uv, so the same codebase registers against different indexes
depending on the environment:

- **Dev** (`.env.dev`): gateway at `http://localhost:8000/simple/`
- **Prod** (`.env.prod`): gateway at the configured URL

> Requires `techneos-management >= 0.1`; catalog packages pin it.

### Gateway

The register scripts talk to the gateway at `PLATFORM_API_URL` and link to the
portal at `PLATFORM_PORTAL_URL` — both default to the local stack when unset, and
`bin/register.sh` sources `.env.dev` if present (see [.env.example](.env.example))
so you can point them at a non-default gateway. Login tokens are cached under
`~/.techneos/<env>_token.json`.

## Registering entries

Each content type has an authoring + registration guide under
[`docs/guides/`](docs/guides), added alongside that type's first entry. Quick
reference and all build/register commands are in [AGENTS.md](AGENTS.md).

| Subdir | Authoring artifact | Registered via |
| --- | --- | --- |
| `datasets/` | `dataset_def.json` | `register.py` → `POST /api/v1/datasets` |
| `tools/` | per-tool `pyproject.toml` + `tool_def.json` | `build_and_register.py` → `POST /api/v1/tools` |
| `pipelines/` | `pipeline_def.json` | `register.py` → `POST /api/v1/pipelines` |
| `apps/` | `Dockerfile` + `app_def.json` | `build_and_register.py` → `POST /api/v1/apps` |
| `agents/` | `agent_def.json` + per-agent `pyproject.toml` | `build_and_register.py` → `POST /api/v1/agents` |
| `tasks/` | `task_def.json` | `register.py` → `POST /api/v1/tools` (as `tool_type="human"`; no artifact to build) |

Each entry ships self-contained — none is a uv workspace member; each pins its own
deps so heterogeneous trees (native libraries, compiled extensions, conflicting
version pins) don't fight for one resolution.

## License

The catalog code is licensed under the [Apache License 2.0](LICENSE); see
[NOTICE](NOTICE). Bundled sample data keeps its source terms: PubChem data is
public domain, ZINC20 data is free to use with citation (Irwin et al., *J. Chem.
Inf. Model.* 2020), and the ChEMBL agent queries ChEMBL data, which is licensed
CC BY-SA 3.0 by EMBL-EBI.
