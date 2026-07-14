#!/usr/bin/env python3
"""Register the Biological Assay Request human task with the platform.

A human task is a ``tool_type="human"`` Tool + version — structurally identical to
a tool registration, minus the artifact (no container image or Python package to
build). Reads ``task_def.json`` and registers via ``management.catalog.register_task``.

Usage::

    bin/register.sh tasks/biological-assay             # register
    bin/register.sh tasks/biological-assay --upsert    # recreate if it exists
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from management.catalog import register_task
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    resolve_portal_url,
    start_session,
)

TASK_DIR = Path(__file__).parent
TASK_DEF = json.loads((TASK_DIR / "task_def.json").read_text())
TASK_SLUG = TASK_DEF["slug"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the Biological Assay Request human task with the platform."
    )
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    args = parser.parse_args()

    session = start_session(args)
    print(f"=== Task: {TASK_SLUG} ===")
    tool_id, _ = register_task(session, TASK_DIR, TASK_DEF, upsert=args.upsert)

    print("\n=== Registration complete ===")
    print(f"  Task:    {TASK_SLUG}")
    print(f"  API:     {session.api_url}/api/v1/tools/{tool_id}")
    print(f"  Portal:  {resolve_portal_url(args.env)}/tasks/{tool_id}")


if __name__ == "__main__":
    main()
