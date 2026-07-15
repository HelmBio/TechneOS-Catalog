#!/usr/bin/env python3
"""Register the Hit Triage pipeline with the platform.

A pipeline is not packaged or published — it is a DAG referencing already-registered
tools. This script validates those tools have an active version, then registers the
definition via ``management.catalog.register_pipeline``.

Usage:
    bin/register.sh pipelines/hit-triage             # register
    bin/register.sh pipelines/hit-triage --upsert    # recreate if it exists
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from management.catalog import register_pipeline
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    resolve_portal_url,
    start_session,
)

PACKAGE_DIR = Path(__file__).parent
PIPELINE_DEF = json.loads((PACKAGE_DIR / "pipeline_def.json").read_text())
PIPELINE_SLUG = PIPELINE_DEF["slug"]


def _required_tool_slugs() -> list[str]:
    """Tool slugs referenced by the pipeline steps, de-duplicated, in order."""
    seen: list[str] = []
    for step in PIPELINE_DEF.get("steps", []):
        slug = step.get("tool_slug")
        if slug and slug not in seen:
            seen.append(slug)
    return seen


def _validate_tools(api_url: str, headers: dict) -> None:
    """Assert each referenced tool exists and has an active version (the pipeline
    service rejects creation otherwise) — fail fast with an actionable message."""
    print("=== Pre-flight validation ===")
    missing: list[str] = []
    inactive: list[str] = []
    for slug in _required_tool_slugs():
        resp = httpx.get(f"{api_url}/api/v1/tools/by-slug/{slug}", headers=headers)
        if resp.status_code != 200:
            missing.append(slug)
            print(f"  {slug} — MISSING")
            continue
        tool = resp.json()
        has_active = any(v.get("status") == "active" for v in tool.get("versions", [])) or (
            tool.get("latest_version_status") == "active"
        )
        print(f"  {slug} — {'OK (active)' if has_active else 'no ACTIVE version'}")
        if not has_active:
            inactive.append(slug)

    if missing or inactive:
        if missing:
            print(f"Error: missing tool(s): {', '.join(missing)}", file=sys.stderr)
        if inactive:
            print(f"Error: tool(s) without an active version: {', '.join(inactive)}", file=sys.stderr)
        sys.exit(1)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register the Hit Triage pipeline with the platform."
    )
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip the referenced-tools check"
    )
    args = parser.parse_args()

    session = start_session(args)
    if not args.skip_validation:
        _validate_tools(session.api_url, session.headers)

    print(f"=== Pipeline: {PIPELINE_SLUG} ===")
    pipeline_id = register_pipeline(session, PACKAGE_DIR, PIPELINE_DEF, upsert=args.upsert)

    print("\n=== Registration complete ===")
    print(f"  Pipeline: {PIPELINE_SLUG}")
    print(f"  API:      {session.api_url}/api/v1/pipelines/{pipeline_id}")
    print(f"  Portal:   {resolve_portal_url(args.env)}/pipelines/{pipeline_id}")


if __name__ == "__main__":
    main()
