"""Retrieve peptide records from PubChem and save them as TSV.

Searches PubChem (via the SDQ agent that backs the web UI) for compounds
matching "peptide", fetches each CID's PUG-View record, and extracts the
Biologic Description (Sequence/HELM/PLN/IUPAC/IUPAC Condensed) and SMILES
fields. Successful rows go to data/pubchem/pubchem_peptides_<count>_<date>.tsv;
CIDs that return no extractable data are written to a sibling JSONL with
their raw response for inspection.

Usage:
    uv run python datasets/pubchem-peptides/retrieve_pubchem_peptides.py
    uv run python datasets/pubchem-peptides/retrieve_pubchem_peptides.py --rerun <no_result_jsonl>
"""

import argparse
import csv
import json
import time
from datetime import date
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "pubchem"
TODAY = date.today().isoformat()
# Working filenames during the run; renamed to include the record count once we know it.
WORKING_TSV = DATA_DIR / f"pubchem_peptides_{TODAY}.tsv"
WORKING_JSONL = DATA_DIR / f"pubchem_peptides_no_result_{TODAY}.jsonl"
TSV_FIELDS = ["CID", "Title", "Sequence", "HELM", "PLN", "IUPAC", "IUPAC_Condensed", "SMILES"]
# A CID is considered to have a "result" if any of these parsed fields are populated.
RESULT_FIELDS = ("Sequence", "HELM", "PLN", "IUPAC", "IUPAC_Condensed", "SMILES")
# PubChem rate limit is 5 req/s, so 0.2s is the minimum interval between requests.
MIN_INTERVAL = 0.2
# Slower pacing on retry to give transient issues (429/503) time to clear.
RETRY_MIN_INTERVAL = 1.0


def get_peptide_cids(limit=10000, term="peptide"):
    """Search PubChem for CIDs matching `term` via the SDQ agent.

    SDQ is the same backend the PubChem web UI uses, so result counts match
    https://pubchem.ncbi.nlm.nih.gov/#query=<term>. Returns up to `limit` CIDs
    as ints.
    """
    url = "https://pubchem.ncbi.nlm.nih.gov/sdq/sdqagent.cgi"
    query = {
        "select": "cid",
        "collection": "compound",
        "where": {"ands": [{"*": term}]},
        "start": 1,
        "limit": limit,
        "listids": 0,
    }
    params = {
        "infmt": "json",
        "outfmt": "json",
        "query": json.dumps(query, separators=(",", ":")),
    }
    response = requests.get(url, params=params)
    if response.status_code != 200:
        return []
    data = response.json()
    output = data.get("SDQOutputSet", [])
    if not output:
        return []
    rows = output[0].get("rows", [])
    return [row["cid"] for row in rows if "cid" in row]


def _find_node(nodes, label):
    """Recursively find the first section/subsection with the given TOCHeading."""
    for node in nodes:
        if node.get("TOCHeading") == label:
            return node
        if "Section" in node:
            res = _find_node(node["Section"], label)
            if res:
                return res
    return None


class MissingRecord(Exception):
    """Raised when PUG-View returns 404 — could be transient or permanent.

    The caller decides: retry once, and if we 404 again, treat as final.
    """

    def __init__(self, cid, body):
        self.cid = cid
        self.body = body
        super().__init__(f"CID {cid}: 404 from PUG-View")


def get_peptide_details(cid, timeout=30):
    """Retrieves Title, biologic line notations, and SMILES from PUG-View.

    Pulls the full PUG-View record in a single request so we can parse both
    the "Biologic Description" section (HELM/PLN/Sequence/IUPAC) and the
    "Names and Identifiers" section (SMILES) in one round-trip. PubChem's
    5 req/s rate limit is the binding constraint, so saving requests beats
    saving bytes for our workload.

    Returns a tuple (details, raw_json) on success.

    Raises:
      MissingRecord: on HTTP 404 (PubChem can return these transiently under
        load, so the caller should retry before treating it as final).
      requests.HTTPError / RequestException: on other transient failures.
    """
    url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
    response = requests.get(url, timeout=timeout)
    if response.status_code == 404:
        try:
            body = response.json()
        except ValueError:
            body = None
        raise MissingRecord(cid, body)
    response.raise_for_status()

    data = response.json()
    details = {
        "CID": cid,
        "Title": None,
        "Sequence": None,
        "HELM": None,
        "PLN": None,
        "IUPAC": None,
        "IUPAC_Condensed": None,
        "SMILES": None,
    }

    record = data.get("Record", {})
    sections = record.get("Section", [])

    details["Title"] = record.get("RecordTitle")

    # Biologic Line Notation lives under "Biologic Description".
    line_notation = _find_node(sections, "Biologic Line Notation")
    if line_notation:
        for info in line_notation.get("Information", []):
            name = info.get("Name")
            string_with_markup = info.get("Value", {}).get("StringWithMarkup", [])
            if not string_with_markup:
                continue
            value = string_with_markup[0].get("String")
            if name == "Sequence":
                details["Sequence"] = value
            elif name == "HELM":
                details["HELM"] = value
            elif name == "PLN":
                details["PLN"] = value
            elif name == "IUPAC":
                details["IUPAC"] = value
            elif name == "IUPAC Condensed":
                details["IUPAC_Condensed"] = value

    # SMILES lives under "Names and Identifiers" → "Computed Descriptors" → "SMILES".
    # Its Information entry has no Name field — just a single value.
    smiles_section = _find_node(sections, "SMILES")
    if smiles_section:
        for info in smiles_section.get("Information", []):
            string_with_markup = info.get("Value", {}).get("StringWithMarkup", [])
            if string_with_markup:
                details["SMILES"] = string_with_markup[0].get("String")
                break

    return details, data


def _write_no_result(cid, reason, response, no_result_f):
    record = {"cid": cid, "reason": reason, "response": response}
    no_result_f.write(json.dumps(record) + "\n")
    no_result_f.flush()


def _fetch_one(cid, writer, tsv_f, no_result_f):
    """Fetch one CID. Streams a TSV row when extractable data is present,
    otherwise appends the raw response to the no-result JSONL file.

    Returns True iff a TSV row was written. May raise MissingRecord (404) or
    other transient errors — the caller decides whether to retry.
    """
    details, raw_json = get_peptide_details(cid)
    if any(details.get(k) for k in RESULT_FIELDS):
        writer.writerow(details)
        tsv_f.flush()
        return True

    _write_no_result(cid, "no_extractable_data", raw_json, no_result_f)
    return False


def load_cids_from_no_result(path):
    """Read CIDs from a no-result JSONL file (one record per line)."""
    cids = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            cid = record.get("cid")
            if cid is not None:
                cids.append(cid)
    return cids


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve peptide records from PubChem and write them to TSV.",
    )
    parser.add_argument(
        "--rerun",
        metavar="JSONL",
        type=Path,
        help="Skip the SDQ peptide search and fetch CIDs listed in this "
        "no-result JSONL file (produced by a previous run).",
    )
    args = parser.parse_args()

    if args.rerun:
        cids = load_cids_from_no_result(args.rerun)
        print(f"Loaded {len(cids)} CIDs from {args.rerun}")
    else:
        cids = get_peptide_cids(limit=10000)
        print(f"Found {len(cids)} peptide CIDs")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    no_result = 0
    failed = []  # CIDs where the request errored (transient — worth retrying)

    try:
        with (
            WORKING_TSV.open("w", newline="", encoding="utf-8") as tsv_f,
            WORKING_JSONL.open("w", encoding="utf-8") as nr_f,
        ):
            writer = csv.DictWriter(tsv_f, fieldnames=TSV_FIELDS, delimiter="\t")
            writer.writeheader()
            tsv_f.flush()

            # First pass — both transient errors and 404s queue for retry.
            # PubChem can return 404 transiently under load, so we don't trust
            # a single 404 as the final answer.
            for i, cid in enumerate(cids, 1):
                start = time.monotonic()
                print(f"[{i}/{len(cids)}] CID {cid}...")
                try:
                    if _fetch_one(cid, writer, tsv_f, nr_f):
                        written += 1
                    else:
                        no_result += 1
                except MissingRecord:
                    print("  404 — will retry")
                    failed.append(cid)
                except Exception as e:
                    print(f"  failed ({type(e).__name__}): {e}")
                    failed.append(cid)
                # Sleep only the remainder; if the fetch already took >= MIN_INTERVAL,
                # don't sleep at all.
                remaining = MIN_INTERVAL - (time.monotonic() - start)
                if remaining > 0:
                    time.sleep(remaining)

            # Retry pass — single sweep over CIDs that errored, with longer backoff.
            # On this pass, a repeat 404 is accepted as final (written to no-result).
            if failed:
                retry_queue = list(failed)
                failed.clear()
                print(f"\nRetrying {len(retry_queue)} failed CIDs...")
                for i, cid in enumerate(retry_queue, 1):
                    start = time.monotonic()
                    print(f"[retry {i}/{len(retry_queue)}] CID {cid}...")
                    try:
                        if _fetch_one(cid, writer, tsv_f, nr_f):
                            written += 1
                        else:
                            no_result += 1
                    except MissingRecord as exc:
                        _write_no_result(cid, "404", exc.body, nr_f)
                        no_result += 1
                    except Exception as e:
                        print(f"  retry failed ({type(e).__name__}): {e}")
                        failed.append(cid)
                    remaining = RETRY_MIN_INTERVAL - (time.monotonic() - start)
                    if remaining > 0:
                        time.sleep(remaining)
    finally:
        # Files are closed at this point; rename to include the record count.
        final_tsv = DATA_DIR / f"pubchem_peptides_{written}_{TODAY}.tsv"
        final_jsonl = DATA_DIR / f"pubchem_peptides_no_result_{no_result}_{TODAY}.jsonl"
        if WORKING_TSV.exists():
            WORKING_TSV.replace(final_tsv)
        if WORKING_JSONL.exists():
            WORKING_JSONL.replace(final_jsonl)
        print(f"\nWrote {written} rows to {final_tsv}")
        print(f"Wrote {no_result} no-result responses to {final_jsonl}")
        if failed:
            print(f"Persistent failures ({len(failed)}): {failed}")


if __name__ == "__main__":
    main()
