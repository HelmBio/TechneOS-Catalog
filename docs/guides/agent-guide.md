# Agent Building Guide

This guide covers how to build, register, and deploy AI agents on the TechneOS
platform. It explains the architecture, walks through writing agent tools, wiring
up the PydanticAI bridge, and registering agent definitions — using the
**ChEMBL Research Assistant** (`agents/chembl/`) as the reference implementation.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Key Concepts](#key-concepts)
3. [LLM Provider Registry](#llm-provider-registry)
4. [Creating Agent Tools](#creating-agent-tools)
5. [The Bridge Layer](#the-bridge-layer)
6. [SSE Streaming Endpoint](#sse-streaming-endpoint)
7. [Multi-Turn Agentic Runs](#multi-turn-agentic-runs)
8. [Frontend Integration](#frontend-integration)
9. [Registering the ChEMBL Agent](#registering-the-chembl-agent)
10. [Testing](#testing)
11. [Adding a New Agent — Step by Step](#adding-a-new-agent--step-by-step)

---

## Architecture Overview

```
AgentDefinition (DB)
  │
  ├── model_config_["provider"]     → LLMProviderRegistry
  │     → ProviderConfig.build_client()  → AsyncOpenAI
  │       → OpenAIProvider → OpenAIChatModel
  │
  ├── system_prompt                 → Agent instructions
  ├── tools[]                       → Resolved via ToolRegistry
  │     → get_tool_registry().resolve(names)
  │
  └── bridge.build_agent_from_definition()
        → PydanticAI Agent instance
          → agent.iter() with SSE events
```

The agent system connects four layers:

| Layer | Component | Location |
|-------|-----------|----------|
| **Provider** | `LLMProviderRegistry` + `ProviderConfig` | `core.agent.registry` |
| **Bridge** | `build_agent_from_definition()` | `core.agent.bridge` |
| **Tools** | Tool functions shipped by the agent's wheel | `chembl_agent.tools` |
| **Tool Registry** | `ToolRegistry` singleton (self-registration + discovery) | `core.agent.tool_registry` |
| **Execution** | SSE streaming endpoint | `agent_service.routes.runs` |
| **Storage** | `AgentDefinition`, `AgenticTask`, `AgenticRun` ORM models | `core.models.agent` |

---

## Key Concepts

### Agent Definition

An `AgentDefinition` is a database record that describes an agent:

| Field | Purpose |
|-------|---------|
| `name` / `slug` | Human-readable name and URL-safe identifier |
| `agent_type` | `conversational`, `autonomous`, etc. |
| `framework` | `pydantic-ai` (currently the only supported framework) |
| `system_prompt` | Instructions passed to the LLM |
| `model_config_` | JSONB with `provider` slug and `model` name |
| `tools` | JSONB list of tool function names or tool set names |
| `default_parameters` | Default runtime parameters (temperature, max_tokens) |
| `parameters_schema` | JSON Schema for parameter validation |
| `tags` | Searchable tags |
| `is_public` | Whether visible to all orgs |

### Agentic Task

An `AgenticTask` records a single execution:

| Field | Purpose |
|-------|---------|
| `agent_id` | FK to `AgentDefinition` |
| `agentic_run_id` | FK to `AgenticRun` (optional, for multi-turn) |
| `task` | The user's prompt |
| `status` | `pending` → `running` → `completed` / `failed` / `cancelled` |
| `result` | JSONB with the agent's response |
| `messages` | Full PydanticAI message history (for agentic run replay) |
| `tool_calls` | List of tool invocations with args |
| `tokens_used` | Total token count |

### Agentic Run

An `AgenticRun` groups multiple `AgenticTask` records for multi-turn chat:

| Field | Purpose |
|-------|---------|
| `agent_id` | FK to `AgentDefinition` (nullable) |
| `title` | User-editable conversation title |
| `summary` | Auto-generated summary (optional) |
| `org_id` / `created_by` | Ownership for RBAC scoping |

---

## LLM Provider Registry

The `LLMProviderRegistry` maps provider slugs to `ProviderConfig` instances
that know how to build `AsyncOpenAI` clients. Providers are loaded from the
`llm_providers` database table at agent service startup.

### How it works

```python
from core.agent.registry import get_registry

registry = get_registry()
provider = registry.get("<provider-slug>")  # ProviderConfig
client = provider.build_client()            # AsyncOpenAI(api_key=..., base_url=...)
```

> **`<provider-slug>` is platform configuration, not catalog content.** LLM providers
> are registered on the platform (admin API / admin UI), and an agent's
> `model_config.provider` must name one that exists there. A fresh deployment
> registers a default provider you can point at; substitute your own slug
> throughout this guide.

### Provider configuration

Each `LLMProvider` DB row contains:

| Field | Example |
|-------|---------|
| `slug` | `<provider-slug>` |
| `base_url` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `encrypted_api_key` | `gAAAAAB...` (Fernet-encrypted) |
| `default_model` | `gemini-2.0-flash` |
| `is_default` | `true` |

The API key is encrypted at rest using Fernet symmetric encryption and decrypted
at runtime by `ProviderConfig.api_key`. Set the key via the admin UI or the
`POST /admin/llm-providers` API — pass the raw key as `api_key`; it will be
encrypted before storage.

### Fallback behavior

If the DB-based lookup fails (table missing, no matching slug), the registry
scans for well-known environment variables in this order:

1. `OPENAI_API_KEY` → standard OpenAI
2. `GEMINI_API_KEY` / `GOOGLE_API_KEY` → Gemini via OpenAI-compatible endpoint

### Adding a new provider

1. Insert a row into `llm_providers` (via admin UI or API)
2. Provide the API key as `api_key` in the request — it will be Fernet-encrypted before storage
3. Restart the agent service

---

## Creating Agent Tools

Tools are plain `async` Python functions with type annotations and docstrings.
PydanticAI auto-generates function-calling schemas from these — no manual JSON
schema definitions needed.

A catalog agent's tools call external APIs directly — the wheel ships only its
tool callables, so it needs no dependency injection and no platform imports:

```python
# chembl_agent/tools.py (the agent package)

async def chembl_search_compounds(query: str, limit: int = 10) -> dict:
    """Search ChEMBL for compounds matching a free-text query.

    Use this tool when the user asks about a drug, compound, molecule, or
    chemical substance by name, synonym, or partial name.

    Args:
        query: Search term — compound name, synonym, or keyword.
        limit: Maximum number of results to return. Defaults to 10.

    Returns:
        A dict with a ``compounds`` list and ``total`` count.
    """
    data = await _chembl_get("/molecule/search.json", params={"q": query, "limit": limit})
    # ... process and return
```

Key rules:
- **Docstring is critical** — PydanticAI uses it to tell the LLM when and how to use the tool
- **Type hints are required** — they become the function-calling schema
- **Return a dict** — PydanticAI serializes it as the tool result
- **Handle errors gracefully** — return `{"error": "..."}` instead of raising

### Registering tools

After creating tool functions, add them to a convenience list at the
bottom of your tools module:

```python
# my_agent/tools.py
MY_TOOLS = [my_search, my_get_record, ...]
```

Then re-export it from the package root so the agent service can pick
it up by introspection:

```python
# my_agent/__init__.py
from my_agent.tools import MY_TOOLS

__all__ = ["MY_TOOLS"]
```

**Do not** call `get_tool_registry().register_set(...)` at import time.
The agent service handles registration explicitly after loading the
entry point — this keeps your wheel free of any compile-time dependency
on `core.agent.tool_registry`, which is what lets the package ship as
a regular pip-installable wheel that the platform installs from the
package index.

For standalone agent packages (like ChEMBL), declare the entry point in
your `pyproject.toml` so the agent service discovers and loads the
package at startup:

```toml
[project.entry-points."techneos.agents"]
my_agent = "my_agent_package"
```

The agent service's `lifespan` handler enumerates `techneos.agents` entry
points, loads each module, looks for either a top-level `TOOLS` list or
a `<NAME>_TOOLS` list (e.g. `CHEMBL_TOOLS`), and registers those
callables with the global `ToolRegistry`.

### Current tool inventory

| Tool Set | Location | Tools | Dependencies |
|----------|----------|-------|--------------|
| **chembl** (5) | `agents/chembl/src/chembl_agent/tools.py` | `chembl_search_compounds`, `chembl_get_compound`, `chembl_get_bioactivities`, `chembl_search_targets`, `chembl_get_target` | None (external ChEMBL API) |

### Versioning

Agent definitions store `tools` as a flat list of function names resolved from
the in-process `ToolRegistry` — no versioning lives at the agent-definition
layer. Pinning happens one level lower, in the package that actually supplies
the function.

For a **catalog agent**, that package is the agent's own wheel: the version the
platform runs is whatever `package_config` records at registration time, which
the agent service installs from the package index at startup. So publishing a new
wheel doesn't change a running agent's behaviour until it is re-registered and the
agent service restarts — the tool set is a snapshot, not a live binding to
"whatever is newest." The function-name list in the `AgentDefinition` row doesn't
need to change when the implementation does.

---

## The Bridge Layer

The bridge (`core.agent.bridge`) translates database agent definitions into
live PydanticAI `Agent` instances.

### `build_agent_from_definition(agent_def)`

This is the main entry point. It:

1. Reads `model_config_` to get the provider slug and model name
2. Calls `build_model_from_provider()` to create an `OpenAIChatModel`
3. Calls `_resolve_tools()` to determine which tools and deps to attach
4. Constructs and returns a `PydanticAI Agent`

### Tool resolution (`_resolve_tools`)

Tools are resolved from the `ToolRegistry` by the bridge:

1. If `agent_def.tools` is empty, all registered tools from the `ToolRegistry` are used
2. If `agent_def.tools` has entries, each name is looked up in the registry via `get_tool_registry().resolve(names)` — names can be individual tool function names or set names

The bridge keeps no hardcoded tool registry. Agent packages self-register and are
discovered at startup via entry points.

### Catalog agents don't build agents — the service does

A **catalog** agent wheel is tool-only: it ships the tool callables and
`agent_def.json`, and nothing else. It does **not** import `pydantic-ai` or build a
PydanticAI `Agent` — the agent-service does that from the registered DB row:

```python
# Production path: build from any AgentDefinition record
# (uses ToolRegistry for tool resolution; reads system_prompt/model_config
#  from the DB row, originally loaded from the agent's agent_def.json)
agent = build_agent_from_definition(agent_def)
```

This is what keeps a catalog agent's wheel small: no `pydantic-ai`, no `core`,
no builder of its own — just the tool callables and a definition.

---

## SSE Streaming Endpoint

The `POST /api/v1/agentic-tasks/stream` endpoint executes agents and streams
results as Server-Sent Events.

### Request

```json
{
  "agent_id": "uuid",
  "task": "What datasets are available for EGFR?",
  "context": {},
  "parameters": {},
  "agentic_run_id": "uuid"    // optional, for multi-turn
}
```

### SSE event types

| Event | Fields | When |
|-------|--------|------|
| `run_started` | `run_id`, `agentic_run_id` | Immediately after run creation |
| `token` | `text` | Each streamed text chunk |
| `tool_call` | `name`, `args` | When the agent invokes a tool |
| `tool_result` | `name`, `result` | After a tool returns |
| `completed` | `text`, `run_id`, `agentic_run_id`, `tokens_used` | Final result |
| `error` | `message`, `run_id` | If execution fails |

### Execution flow

1. Validate agent definition and RBAC access
2. Handle agentic run (use an existing one, or auto-create for conversational agents)
3. Load message history from prior agentic run tasks
4. Create `AgenticTask` record with status `pending`
5. Build PydanticAI agent via `build_agent_from_definition()`
6. Update status to `running`
7. Execute `agent.iter()` with `user_prompt` and `message_history`
8. Stream tool calls (before execution) and tool results as SSE events in real-time
9. On completion, save result, messages, tool calls, and tokens to the run record
10. On error, save error message and update status to `failed`

---

## Multi-Turn Agentic Runs

Agentic runs enable multi-turn chat by linking multiple `AgenticTask` records
together and replaying message history.

### How it works

1. **First message**: No `conversation_id` → a new `Conversation` is auto-created (for conversational agents)
2. **Subsequent messages**: Client sends `conversation_id` from the `run_started` event
3. **History loading**: The endpoint calls `get_conversation_messages()` which collects all `messages` from prior completed runs in the conversation
4. **History injection**: The collected messages are passed as `message_history` to PydanticAI's `agent.iter()`, giving the LLM full context

### Agentic Run API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/agentic-runs` | Create a new agentic run |
| `GET` | `/api/v1/agentic-runs` | List agentic runs (filter by `agent_id`) |
| `GET` | `/api/v1/agentic-runs/{id}` | Get agentic run with all tasks |
| `PATCH` | `/api/v1/agentic-runs/{id}` | Update agentic run (rename title) |
| `DELETE` | `/api/v1/agentic-runs/{id}` | Delete agentic run and its tasks |

### Database model

```sql
conversations
  ├── id (UUID PK)
  ├── agent_id (FK → agents)
  ├── title (VARCHAR 500, nullable)
  ├── summary (TEXT, nullable)
  ├── metadata (JSONB)
  ├── org_id (FK → orgs)
  ├── created_by (FK → users)
  ├── created_at / updated_at
  └── tasks[] (via AgenticTask.agentic_run_id FK)
```

---

## Frontend Integration

Your agent gets a chat interface in the web portal for free — no frontend work is
needed to register one. This section describes how that interface talks to the
streaming endpoint, in case you are building your own client.

### SSE consumption pattern

All SSE consumers use the shared `ssePost()` helper from `api.ts`:

```typescript
import { ssePost } from "@/lib/api";

const resp = await ssePost("/api/v1/agentic-tasks/stream", {
  agent_id: agent.id,
  task: userMessage,
  agentic_run_id: agenticRunId,  // null for first message
});

const reader = resp.body?.getReader();
const decoder = new TextDecoder();
let buffer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split("\n");
  buffer = lines.pop() || "";

  for (const line of lines) {
    if (!line.startsWith("data: ")) continue;
    const parsed = JSON.parse(line.slice(6));

    switch (parsed.type) {
      case "run_started":
        setAgenticRunId(parsed.agentic_run_id);
        break;
      case "token":
        appendText(parsed.text);
        break;
      case "tool_call":
        addToolCall(parsed.name, parsed.args);
        break;
      case "completed":
        // Done
        break;
      case "error":
        showError(parsed.message);
        break;
    }
  }
}
```

The `ssePost()` helper handles 401/403 → token refresh → retry automatically.

### Agent detail page (`/agents/[id]`)

Each registered agent's detail page includes a chat interface for testing it
directly — this is where you exercise your agent after registering it.

---

## Registering the ChEMBL Agent

```bash
bin/register.sh agents/chembl
```

Builds the `chembl-agent` wheel with `uv build`, publishes it to the configured
Python package index (the local devpi), and creates or PATCHes the ChEMBL Research
Assistant `AgentDefinition` in the platform — including the `package_config` field
the agent-service uses to install the wheel at startup. Arguments pass through to
the underlying script: `--skip-build`, `--skip-publish`, `--upsert`. See
[`agents/chembl/build_and_register.py`](../../agents/chembl/build_and_register.py).

To remove: `./bin/agent_removal.sh chembl-research-assistant`.

### Custom Agents

Custom agents are created by mirroring the chembl-agent layout under
`agents/<slug>/`, then running its `build_and_register.py`.
The platform DB row stores `package_config = {name, version,
index_url, entry_point}`; on agent-service startup, each registered
agent's wheel is `pip install`ed from the configured index before
`techneos.agents` entry points are enumerated. No platform-code change is
needed to register a new agent.

If your agent has heavy or unusual deps (RDKit pins, native libs),
declare them in your `pyproject.toml` just like a normal Python package
— each agent's wheel resolves independently of the platform and of
other agents.

---

## Testing

### Unit tests

Each agent package owns its tests. The ChEMBL agent's live in
`agents/chembl/tests/`:

| File | Count | What it tests |
|------|-------|---------------|
| `test_chembl_tools.py` | 11 | All 5 ChEMBL tools (success + error paths) |

Run them from the package directory:

```bash
cd agents/chembl
uv sync --group dev
uv run pytest
```

The bridge and the provider registry are the platform's concern and are tested in
the platform repo, not here.

### Testing pattern

Tools are tested by mocking the external API (httpx) and verifying the response
structure — no platform, DB, or network dependency:

```python
@pytest.mark.asyncio
async def test_chembl_search_compounds():
    with respx.mock:
        respx.get("https://www.ebi.ac.uk/chembl/api/data/molecule/search.json").mock(
            return_value=httpx.Response(200, json={"molecules": [...]})
        )
        result = await chembl_search_compounds("aspirin")
        assert "compounds" in result
```

---

## Adding a New Agent — Step by Step

This checklist walks through creating a new agent from scratch.

### 1. Define your tools

Create a new file in your catalog package, e.g.
`agents/my-agent/src/my_agent_package/tools.py`:

```python
from __future__ import annotations
import httpx

async def my_search(query: str, limit: int = 10) -> dict:
    """Search my external API for results.

    Use this tool when the user asks about [your domain].

    Args:
        query: Search term.
        limit: Maximum results to return.

    Returns:
        A dict with results.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get("https://my-api.com/search", params={"q": query, "limit": limit})
        resp.raise_for_status()
        return resp.json()

MY_TOOLS = [my_search]
```

### 2. Expose tools via the package's `__init__.py`

Re-export your tools list so the agent service can find it after
loading the entry point. **Do not** call `get_tool_registry()` at
import time — the runtime does the registration explicitly so your
wheel doesn't grow a compile-time `core` dep.

```python
# my_agent_package/__init__.py
from my_agent_package.tools import MY_TOOLS

__all__ = ["MY_TOOLS"]
```

Then add an entry point in your agent package's `pyproject.toml`:

```toml
[project.entry-points."techneos.agents"]
my_agent = "my_agent_package"

[tool.techneos]
delivery = "pypi"
package_name = "my-agent"
entry_point = "my_agent_package"
```

At agent-service startup, the lifespan handler:
1. Reads `AgentDefinition.package_config` for every registered agent and
   `pip install`s each one from the configured Python package index.
2. Enumerates `techneos.agents` entry points, loads each module, and
   registers its `<NAME>_TOOLS` list with the global `ToolRegistry`.

### 3. Write `agent_def.json` and the build_and_register script

Create two files at `agents/my-agent/`:

**`agent_def.json`** — the full `POST /agents` body, mirroring the
`dataset_def.json` convention. Everything that's known at authoring
time goes here; only `package_config` is filled in at registration time.

```json
{
  "name": "My Agent",
  "slug": "my-agent",
  "description": "What this agent does.",
  "agent_type": "conversational",
  "framework": "pydantic-ai",
  "system_prompt": "You are ...",
  "tools": ["my_search"],
  "model_config": {
    "provider": "<provider-slug>",
    "model": "<model-name>",
    "max_tokens": null,
    "temperature": 0.1
  },
  "parameters_schema": {"type": "object", "properties": {}},
  "default_parameters": {},
  "tags": ["my-domain"],
  "is_public": true,
  "is_platform": false
}
```

**`build_and_register.py`** — ~50 lines, mirroring
[`agents/chembl/build_and_register.py`](../../agents/chembl/build_and_register.py):
constants + any pre-flight check + a single
`management.catalog.register_agent` (`packages/management/src/management/catalog.py` in the platform repo)
call. `register_agent` does the orchestration for you:

1. Builds + publishes the wheel and **records it** in the `compute_artifacts`
   inventory (`origin=catalog`) **before** registering the agent — fatal, because
   agent registration hard-validates `package_config` against an `available` wheel
   row (422 otherwise).
2. Computes `package_config = {name, version, entry_point}` from `pyproject.toml`
   (`index_url` is left out — it's environmental, resolved at install time).
3. POSTs `agent_def.json` (with `package_config` spliced in) to `/api/v1/agents`,
   or PATCHes `model_config` + `package_config` on an existing row.

```python
from management.catalog import register_agent
from management.registration import add_auth_args, add_env_arg, add_upsert_arg, start_session
# ... parse args, then:
session = start_session(args)
register_agent(session, PACKAGE_DIR, AGENT_DEF,
               skip_build=args.skip_build, skip_publish=args.skip_publish, upsert=args.upsert)
```

### 4. Register the agent

```bash
bin/register.sh agents/my-agent
```

Then **restart the platform's agent service** so it picks up the new
`package_config` and `pip install`s your wheel from the package index.

To remove your agent later:

```bash
./bin/agent_removal.sh my-agent
```

### 5. Write tests

Create `agents/my-agent/tests/test_my_tools.py`:

```python
import pytest
import httpx
import respx

@pytest.mark.asyncio
async def test_my_search():
    with respx.mock:
        respx.get("https://my-api.com/search").mock(
            return_value=httpx.Response(200, json={"results": [...]})
        )
        result = await my_search("test")
        assert "results" in result
```

### 6. Tool resolution

No changes to the bridge are needed — the `ToolRegistry` automatically resolves
tool names when building agents via `build_agent_from_definition()`. Ensure your
tool names are included in the agent definition's `tools` array.

### 7. Test end-to-end

1. Make sure the platform's dev stack is running (agent service + gateway)
2. Navigate to `/agents` in the web portal
3. Find your agent and open its detail page
4. Use the chat interface to test

### 8. Update documentation

- Update [AGENTS.md](../../AGENTS.md) with the new agent package and entry point
- Update this guide if you discover new patterns worth documenting

---

## See Also

- [Dataset Registration Guide](dataset-guide.md) — Registering and versioning datasets (ZINC20 example)
