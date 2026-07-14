#!/usr/bin/env python
"""Build and register autodock-vina (container-only) with the platform.

Builds + pushes the Docker image (non-local), records it, and upserts the Tool +
container ToolVersion via ``management.catalog.register_container_tool``.

    uv run --group tooling python tools/autodock-vina/build_and_register.py            # local build
    uv run --group tooling python tools/autodock-vina/build_and_register.py --env=local --upsert
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

from management.catalog import register_container_tool
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    read_package_meta,
    resolve_portal_url,
    start_session,
)

PACKAGE_DIR = Path(__file__).parent
TOOL_DEF = json.loads((PACKAGE_DIR / "tool_def.json").read_text())
TOOL_SLUG = TOOL_DEF["slug"]


def _entrypoint_spec() -> str:
    """The module:function the generic runtime invokes — read from the Dockerfile."""
    text = (PACKAGE_DIR / "Dockerfile").read_text()
    match = re.search(r"^ENV\s+ENTRYPOINT_SPEC=(\S+)", text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find `ENV ENTRYPOINT_SPEC=...` in Dockerfile")
    return match.group(1)


def _validate() -> None:
    """Static (ast, no import) check that ENTRYPOINT_SPEC resolves to a real def."""
    print("=== Pre-flight validation ===")
    spec = _entrypoint_spec()
    mod_path, _, func_name = spec.partition(":")
    src = PACKAGE_DIR / "src"
    module_file = src / f"{Path(*mod_path.split('.'))}.py"
    if not module_file.exists():
        module_file = src / Path(*mod_path.split(".")) / "__init__.py"
    if not module_file.exists():
        print(f"Error: ENTRYPOINT_SPEC module {mod_path!r} has no source under src/", file=sys.stderr)
        sys.exit(1)
    if func_name:
        defined = {
            n.name
            for n in ast.parse(module_file.read_text()).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if func_name not in defined:
            print(f"Error: ENTRYPOINT_SPEC {func_name!r} not defined in {mod_path!r}", file=sys.stderr)
            sys.exit(1)
    print(f"  ENTRYPOINT_SPEC {spec!r} — OK\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Register autodock-vina (container) with TechneOS.")
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    parser.add_argument("--skip-build", action="store_true", help="Skip building & pushing the image")
    parser.add_argument("--skip-push", action="store_true", help="Build but do not push to a remote registry")
    parser.add_argument("--skip-validation", action="store_true", help="Skip the entrypoint check")
    args = parser.parse_args()

    if not args.skip_validation:
        _validate()

    session = start_session(args)
    tool_id, _ = register_container_tool(
        session,
        PACKAGE_DIR,
        TOOL_DEF,
        skip_build=args.skip_build,
        skip_push=args.skip_push,
        upsert=args.upsert,
    )

    print("\n=== Registration complete ===")
    print(f"  Tool:    {TOOL_SLUG}")
    print(f"  Package: {read_package_meta(PACKAGE_DIR).name}")
    print(f"  API:     {session.api_url}/api/v1/tools/{tool_id}")
    print(f"  Portal:  {resolve_portal_url(args.env)}/tools/{tool_id}")


if __name__ == "__main__":
    main()
