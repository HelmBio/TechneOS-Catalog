#!/usr/bin/env python3
"""Register the ZINC20 dataset with the platform.

A dataset has no artifact to build — it is API metadata + an uploaded data file.
Registers via ``management.catalog.register_dataset``.

Usage:
    uv run python datasets/zinc20/register.py --file /path/to/data.tsv
    uv run python datasets/zinc20/register.py                 # uses data/ dir
    uv run python datasets/zinc20/register.py --upsert
    uv run python datasets/zinc20/register.py --new-version
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from management.catalog import register_dataset, resolve_dataset_file
from management.registration import (
    add_auth_args,
    add_env_arg,
    add_upsert_arg,
    resolve_portal_url,
    start_session,
)

HF_DATASET = "zpn/zinc20"
DATASET_DIR = Path(__file__).parent
DATASET_DEF = json.loads((DATASET_DIR / "dataset_def.json").read_text())
DEFAULT_DATA_DIR = DATASET_DIR / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Register the ZINC20 dataset with the platform.")
    add_env_arg(parser)
    add_auth_args(parser)
    add_upsert_arg(parser)
    parser.add_argument("--file", default=None, help="Path to a .tsv file or dir (default: data/)")
    parser.add_argument(
        "--new-version", action="store_true", help="Upload as a new version to an existing dataset"
    )
    parser.add_argument("--force", action="store_true", help="Deprecated alias for --upsert")
    args = parser.parse_args()
    if args.force:
        args.upsert = True

    session = start_session(args)
    data_file, row_count = resolve_dataset_file(args.file, DEFAULT_DATA_DIR)

    DATASET_DEF["description"] = (
        f"A {row_count:,}-molecule sample from the ZINC20 database "
        "(sourced from HuggingFace zpn/zinc20, ~1B molecules total). "
        "Contains purchasable, drug-like compounds with SMILES, SELFIES "
        "representations, and ZINC IDs. Intended as a lightweight reference "
        "dataset for development, testing, and benchmarking. "
        "For the full dataset see https://huggingface.co/datasets/zpn/zinc20"
    )

    dataset_id = register_dataset(
        session,
        DATASET_DEF,
        data_file,
        upsert=args.upsert,
        new_version=args.new_version,
        upload_description=(
            f"{row_count:,}-molecule sample from HuggingFace {HF_DATASET} (train split)"
        ),
    )

    print("\n=== Done ===")
    print(f"  Dataset: {DATASET_DEF['slug']}")
    print(f"  Portal:  {resolve_portal_url(args.env)}/datasets/{dataset_id}")
    print(f"  API:     {session.api_url}/api/v1/datasets/{dataset_id}")


if __name__ == "__main__":
    main()
