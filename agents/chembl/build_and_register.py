#!/usr/bin/env python
"""Build, publish, and register the ChEMBL Research Assistant agent.

Builds + publishes the wheel, records it in the compute-artifact inventory, and
upserts the AgentDefinition (with runtime ``package_config``) — all via the shared
``management.catalog.register_agent`` orchestrator.

    uv run --group tooling python agents/chembl/build_and_register.py            # full
    uv run --group tooling python agents/chembl/build_and_register.py --skip-build
    uv run --group tooling python agents/chembl/build_and_register.py --env=local --upsert
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from chembl_agent.tools import CHEMBL_TOOLS

from management.catalog import register_agent
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    read_package_meta,
    start_session,
)

PACKAGE_DIR = Path(__file__).parent
# The JSON is the POST /api/v1/agents body, minus `package_config` (computed at
# registration time from pyproject.toml). Mirrors dataset_def.json / app_def.json.
AGENT_DEF = json.loads((PACKAGE_DIR / "agent_def.json").read_text())
AGENT_SLUG: str = AGENT_DEF["slug"]


def _check_tool_drift() -> None:
    """Warn (don't fail) if agent_def.json's tool list drifts from CHEMBL_TOOLS.

    The JSON is authoritative for what the platform registers, but CHEMBL_TOOLS is
    what the wheel exports. If they disagree the agent registers with tool names the
    runtime can't resolve — catch it at registration time, not first run.
    """
    declared = set(AGENT_DEF.get("tools", []))
    exported = {fn.__name__ for fn in CHEMBL_TOOLS}
    if declared != exported:
        msg = []
        if declared - exported:
            msg.append(f"in agent_def.json but not CHEMBL_TOOLS: {sorted(declared - exported)}")
        if exported - declared:
            msg.append(f"in CHEMBL_TOOLS but not agent_def.json: {sorted(exported - declared)}")
        print("  Warning: tool drift:\n    " + "\n    ".join(msg), file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build, publish, and register the ChEMBL Research Assistant agent."
    )
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    parser.add_argument("--skip-build", action="store_true", help="Skip building & publishing")
    parser.add_argument("--skip-publish", action="store_true", help="Build but do not publish")
    args = parser.parse_args()

    _check_tool_drift()

    session = start_session(args)
    print(f"=== Agent: {AGENT_SLUG} ===")
    agent_id = register_agent(
        session,
        PACKAGE_DIR,
        AGENT_DEF,
        skip_build=args.skip_build,
        skip_publish=args.skip_publish,
        upsert=args.upsert,
    )

    meta = read_package_meta(PACKAGE_DIR)
    print("\n=== Done ===")
    print(f"  Agent:   {AGENT_SLUG}")
    print(f"  Package: {meta.name}=={meta.version}")
    print(f"  API:     {session.api_url}/api/v1/agents/{agent_id}")


if __name__ == "__main__":
    main()
