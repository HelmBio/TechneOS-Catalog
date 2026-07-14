#!/usr/bin/env python
"""Build and register the Compound Clustering tool with the platform.

A pypi tool (runs in the shared techneos/tool-runtime worker image). Builds + publishes
the wheel, records it, and upserts the Tool + pypi ToolVersion via
``management.catalog.register_pypi_tool``.

    cd tools/compound-clustering && uv run --group publish python build_and_register.py
    cd tools/compound-clustering && uv run --group publish python build_and_register.py --env=local --upsert
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from management.catalog import register_pypi_tool
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    read_package_meta,
    resolve_portal_url,
    start_session,
)

PACKAGE_DIR = Path(__file__).parent
TOOL_SLUG = "compound-clustering"
TOOL_DEF = json.loads((PACKAGE_DIR / "tool_def.json").read_text())
_META = read_package_meta(PACKAGE_DIR)
ENTRY_POINT = _META.entry_point


def _validate() -> None:
    """Pre-flight: assert the entry-point module/function is importable before build."""
    print("=== Pre-flight validation ===")
    mod_path, _, func_name = (ENTRY_POINT or "").partition(":")
    src_dir = str(PACKAGE_DIR / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    try:
        mod = importlib.import_module(mod_path)
    except ImportError as exc:
        print(f"Error: entry_point module {mod_path!r} cannot be imported: {exc}", file=sys.stderr)
        sys.exit(1)
    if func_name and not callable(getattr(mod, func_name, None)):
        print(f"Error: entry_point {func_name!r} not found/callable in {mod_path!r}", file=sys.stderr)
        sys.exit(1)
    print(f"  entry_point {ENTRY_POINT!r} — OK\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the Compound Clustering tool with the platform."
    )
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    parser.add_argument("--skip-build", action="store_true", help="Skip building & publishing")
    parser.add_argument("--skip-publish", action="store_true", help="Build but do not publish")
    parser.add_argument("--skip-validation", action="store_true", help="Skip the entry-point check")
    args = parser.parse_args()

    if not args.skip_validation:
        _validate()

    session = start_session(args)
    tool_id, _ = register_pypi_tool(
        session,
        PACKAGE_DIR,
        TOOL_DEF,
        skip_build=args.skip_build,
        skip_publish=args.skip_publish,
        upsert=args.upsert,
    )

    print("\n=== Registration complete ===")
    print(f"  Tool:    {TOOL_SLUG}")
    print(f"  Package: {_META.name}")
    print(f"  API:     {session.api_url}/api/v1/tools/{tool_id}")
    print(f"  Portal:  {resolve_portal_url(args.env)}/tools/{tool_id}")


if __name__ == "__main__":
    main()
