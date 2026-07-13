#!/usr/bin/env python3
"""Download ZINC20 molecules from HuggingFace into the data/ directory.

Usage:
    uv run python datasets/zinc20/download_from_huggingface.py
    uv run python datasets/zinc20/download_from_huggingface.py --count 50000
    uv run python datasets/zinc20/download_from_huggingface.py --output /path/to/output.tsv
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from pathlib import Path

import httpx

HF_DATASET = "zpn/zinc20"
DEFAULT_COUNT = 20_000
DEFAULT_OUTPUT = Path(__file__).parent / "data" / "zinc20_druglike.tsv"


def download_from_huggingface(dest: Path, count: int) -> int:
    """Stream molecules from HuggingFace JSONL.gz files. Returns row count."""
    print(f"Downloading {count:,} molecules from HuggingFace ({HF_DATASET})...")

    hf_base = "https://huggingface.co/datasets/zpn/zinc20/resolve/main/zinc_processed"

    rows_written = 0
    shard_idx = 0

    dest.parent.mkdir(parents=True, exist_ok=True)

    with open(dest, "w", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["smiles", "selfies", "zinc_id"])

        while rows_written < count:
            shard_name = f"smiles_all_{shard_idx:02d}_clean.jsonl.gz"
            url = f"{hf_base}/{shard_name}"
            print(f"  Streaming {shard_name}...")

            resp = httpx.get(url, follow_redirects=True, timeout=120.0)
            if resp.status_code == 404:
                print(f"  ERROR: Shard {shard_name} not found. Only got {rows_written:,} rows.")
                sys.exit(1)
            if resp.status_code != 200:
                print(f"  ERROR: HTTP {resp.status_code} for {shard_name}")
                sys.exit(1)

            gz = gzip.GzipFile(fileobj=io.BytesIO(resp.content))
            for raw_line in gz:
                if rows_written >= count:
                    break
                row = json.loads(raw_line)
                smiles = row.get("smiles", "")
                if not smiles:
                    continue
                selfies = row.get("selfies", "")
                zinc_id = row.get("id", "")
                writer.writerow([smiles, selfies, zinc_id])
                rows_written += 1

            print(f"  Progress: {rows_written:,} / {count:,} molecules")
            shard_idx += 1

    if rows_written < count:
        print(f"  ERROR: Only got {rows_written:,} of {count:,} requested molecules.")
        sys.exit(1)

    size = dest.stat().st_size
    print(f"  Done: {rows_written:,} molecules, {size:,} bytes")
    return rows_written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download ZINC20 molecules from HuggingFace into the data/ directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output TSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Number of molecules to download (default: {DEFAULT_COUNT:,})",
    )
    args = parser.parse_args()

    row_count = download_from_huggingface(args.output, args.count)
    print(f"\nDownloaded {row_count:,} molecules to {args.output}")


if __name__ == "__main__":
    main()
