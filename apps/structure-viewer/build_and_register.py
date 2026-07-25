#!/usr/bin/env python3
"""Build, register, and deploy the Structure Viewer embedded app.

Builds the Docker image, records it, upserts the App, and triggers a deploy — all
via ``management.catalog.register_app``. The image tag is ``package.json``'s version.

Usage:
    bin/register.sh apps/structure-viewer
    bin/register.sh apps/structure-viewer --upsert
    bin/register.sh apps/structure-viewer --skip-build   # | --skip-deploy

Removal:
    ./bin/unregister.sh app structure-viewer
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from management.catalog import register_app
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    resolve_portal_url,
    start_session,
)

APP_DIR = Path(__file__).parent
APP_DEF = json.loads((APP_DIR / "app_def.json").read_text())
APP_SLUG: str = APP_DEF["slug"]


def _app_version() -> str:
    """The docker tag: package.json's ``version`` (the app's source of truth)."""
    pkg = json.loads((APP_DIR / "package.json").read_text())
    if "version" not in pkg:
        print(f"ERROR: no `version` field in {APP_DIR / 'package.json'}", file=sys.stderr)
        sys.exit(1)
    return str(pkg["version"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build, register, and deploy the Structure Viewer app."
    )
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    parser.add_argument("--skip-build", action="store_true", help="Skip the docker build")
    parser.add_argument(
        "--skip-push", action="store_true", help="Build but do not push to a remote registry"
    )
    parser.add_argument("--skip-deploy", action="store_true", help="Register but do not deploy")
    args = parser.parse_args()

    version = _app_version()
    session = start_session(args)
    print(f"=== App: {APP_SLUG} (v{version}) ===")
    app_id = register_app(
        session,
        APP_DIR,
        APP_DEF,
        version=version,
        skip_build=args.skip_build,
        skip_push=args.skip_push,
        skip_deploy=args.skip_deploy,
        upsert=args.upsert,
    )

    print("\n=== Done ===")
    print(f"  App:     {APP_SLUG}")
    print(f"  Version: {version}")
    print(f"  API:     {session.api_url}/api/v1/apps/{app_id}")
    print(f"  Portal:  {resolve_portal_url(args.env)}/apps/{app_id}")


if __name__ == "__main__":
    main()
