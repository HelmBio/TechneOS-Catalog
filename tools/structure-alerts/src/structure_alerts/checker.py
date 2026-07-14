"""
Structure Alerts

Screens compounds (e.g. from an HTS campaign) for PAINS pan-assay-interference
substructures and reactive / unstable functional groups, and reports the
specific reason each compound is flagged.

Matching is delegated to RDKit's built-in ``FilterCatalog`` — the canonical,
literature-reference SMARTS encodings of the published alert sets (PAINS A/B/C,
Brenk, NIH, ZINC, ChEMBL) — plus a small hand-curated reactive-group SMARTS list
on top. We do not re-derive these patterns by hand.

Usage (CLI):
    echo '{"compounds": [{"smiles": "Oc1ccccc1O", "id": "c1"}]}' > input.json
    python -m structure_alerts.checker --input input.json --output output.json

Usage (library):
    from structure_alerts.checker import run
    result = run(
        {"compounds": [{"smiles": "Oc1ccccc1O", "id": "c1"}]},
        {"filter_catalogs": ["PAINS", "BRENK"]},
    )
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

# ── Alert catalogs ───────────────────────────────────────────────────────────
# Friendly name -> RDKit FilterCatalogs enum member. These are the published
# structural-alert sets shipped with RDKit. "ALL" enables every catalog at once.
_CATALOGS = FilterCatalogParams.FilterCatalogs
CATALOG_NAMES: dict[str, object] = {
    "PAINS": _CATALOGS.PAINS,  # Baell & Holloway A+B+C (frequent hitters)
    "PAINS_A": _CATALOGS.PAINS_A,
    "PAINS_B": _CATALOGS.PAINS_B,
    "PAINS_C": _CATALOGS.PAINS_C,
    "BRENK": _CATALOGS.BRENK,  # reactive / toxic / metabolically unstable groups
    "NIH": _CATALOGS.NIH,  # NIH MLSMR excluded functionality
    "ZINC": _CATALOGS.ZINC,  # ZINC drug-like / reactivity rules
    "CHEMBL": _CATALOGS.CHEMBL,  # all ChEMBL sub-sets (Dundee, BMS, Glaxo, ...)
    "ALL": _CATALOGS.ALL,
}

DEFAULT_CATALOGS: list[str] = ["PAINS", "BRENK"]

# ── Custom reactive-group SMARTS ─────────────────────────────────────────────
# A focused list of common reactive electrophiles teams often want flagged on
# top of the catalogs. Overlaps partially with Brenk/NIH by design — when both
# are enabled a compound simply accrues more (informative) reasons. Hand-curated
# here so the list is small, auditable, and independent of any catalog.
_REACTIVE_SMARTS_SRC: list[tuple[str, str]] = [
    ("acyl_halide", "C(=O)[Cl,Br,I,F]"),
    ("sulfonyl_halide", "S(=O)(=O)[Cl,Br,F]"),
    ("aldehyde", "[CX3H1](=O)[#6]"),
    ("michael_acceptor", "[CX3]=[CX3]C(=O)[#6,#1]"),
    ("epoxide", "C1OC1"),
    ("aziridine", "C1CN1"),
    ("isocyanate", "N=C=O"),
    ("isothiocyanate", "N=C=S"),
    ("anhydride", "C(=O)OC(=O)"),
    ("alkyl_halide", "[CX4][Cl,Br,I]"),
    ("boronic_acid_or_ester", "B(O)O"),
    ("nitroso", "[NX2]=O"),
    ("hydrazine", "[NX3][NX3]"),
    ("phosphorus_halide", "P[Cl,Br,F]"),
]

# Compile once at import; a None pattern (bad SMARTS) is skipped at match time.
_REACTIVE_SMARTS: list[tuple[str, Chem.Mol]] = [
    (name, Chem.MolFromSmarts(smarts)) for name, smarts in _REACTIVE_SMARTS_SRC
]


# ── Helpers ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1024)
def smiles_to_mol(smiles: str) -> Chem.Mol | None:
    """Convert SMILES to a sanitized RDKit Mol (cached). None if invalid."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is not None:
        Chem.SanitizeMol(mol)
    return mol


def _validate_compounds(raw_list: list) -> tuple[list[tuple[str, str]] | None, str | None]:
    """Validate the input compounds list.

    Each item must be an object with a non-empty ``smiles`` and a non-empty
    ``id``, and all ids must be unique across the list. These are schema-level
    constraints, so any violation rejects the whole batch with an explanatory
    message (distinct from a present-but-unparseable SMILES, which is reported
    per-compound in ``errors``).

    Returns ``(compounds, error)`` where ``compounds`` is a list of
    ``(smiles, id)`` tuples (or None on failure) and ``error`` is a
    human-readable message (or None on success).
    """
    compounds: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            return None, f"compounds[{i}] must be an object with 'smiles' and 'id'"
        smiles = item.get("smiles")
        cid = item.get("id")
        if not smiles or not isinstance(smiles, str):
            return None, f"compounds[{i}] is missing a non-empty 'smiles'"
        if cid is None or cid == "":
            return None, f"compounds[{i}] is missing a non-empty 'id'"
        cid = str(cid)
        if cid in seen_ids:
            return None, f"duplicate id {cid!r} — every compound 'id' must be unique"
        seen_ids.add(cid)
        compounds.append((smiles, cid))
    return compounds, None


def _error_result(message: str, params: dict) -> dict:
    """Build a uniform empty result carrying a top-level error message."""
    return {
        "error": message,
        "results": [],
        "passed": [],
        "flagged": [],
        "errors": [],
        "summary": {"total": 0, "passed": 0, "flagged": 0, "invalid": 0, "by_source": {}},
        "count": 0,
        "params_used": params,
    }


def _resolve_catalogs(catalogs: list[str]) -> tuple[list[str], list[str]]:
    """Normalize requested catalog names; return (valid_names, unknown_names).

    Names are matched case-insensitively. ``ALL`` short-circuits to just
    ``["ALL"]`` since it already enables everything.
    """
    valid: list[str] = []
    unknown: list[str] = []
    for raw in catalogs:
        name = str(raw).strip().upper()
        if name not in CATALOG_NAMES:
            unknown.append(raw)
        elif name not in valid:
            valid.append(name)
    if "ALL" in valid:
        return ["ALL"], unknown
    return valid, unknown


@lru_cache(maxsize=32)
def _build_catalog(names: tuple[str, ...]) -> FilterCatalog:
    """Build a (cached) FilterCatalog from validated friendly catalog names."""
    params = FilterCatalogParams()
    for name in names:
        params.AddCatalog(CATALOG_NAMES[name])
    return FilterCatalog(params)


def _classify(filter_set: str) -> str:
    """Bucket a FilterSet name into pains | reactive | medchem."""
    fs = filter_set.upper()
    if fs.startswith("PAINS"):
        return "pains"
    if fs.startswith("BRENK") or fs.startswith("NIH"):
        return "reactive"
    return "medchem"


def screen_molecule(
    mol: Chem.Mol,
    catalog: FilterCatalog,
    reactive: list[tuple[str, Chem.Mol]],
) -> list[dict]:
    """Return the list of alerts (reasons) a molecule triggers.

    Each alert is ``{"source", "category", "description"}``. An empty list
    means the molecule is clean against the configured filters.
    """
    alerts: list[dict] = []
    for entry in catalog.GetMatches(mol):
        try:
            filter_set = entry.GetProp("FilterSet")
        except KeyError:
            filter_set = "unknown"
        alerts.append(
            {
                "source": filter_set,
                "category": _classify(filter_set),
                "description": entry.GetDescription(),
            }
        )
    for name, patt in reactive:
        if patt is not None and mol.HasSubstructMatch(patt):
            alerts.append(
                {"source": "reactive_smarts", "category": "reactive", "description": name}
            )
    return alerts


def run(input_data: dict | list, params: dict | None = None) -> dict:
    """Screen a list of compounds for PAINS and reactive-group structural alerts.

    Each compound must be an object ``{"smiles": "...", "id": "..."}`` — both
    fields required — and every ``id`` must be unique across the list. Results
    are keyed by ``id``.

    Args:
        input_data: Either the compounds list directly (a ``list`` of
            ``{"smiles", "id"}`` objects, as the platform delivers it after
            parsing an uploaded file), or a dict carrying that list under a key
            (default ``"compounds"``; the platform auto-injects the actual key
            via the ``smiles_list_key`` param).
        params: Optional dict of options:
            - filter_catalogs (list[str]): Alert sets to apply. Default
              ``["PAINS", "BRENK"]``. Allowed: PAINS, PAINS_A/B/C, BRENK, NIH,
              ZINC, CHEMBL, ALL. (Case-insensitive; ``["ALL"]`` enables every set.)
            - reactive_smarts (bool): Also apply the custom reactive-group SMARTS
              list (default True).
            - smiles_list_key (str): Key under which the compounds list is found
              in ``input_data`` (default ``"compounds"``). Auto-injected by the
              platform from the input_schema's array property.
            - include_passing (bool): Include clean compounds in ``results``
              (default True). The ``passed`` list is always populated regardless.

    Returns:
        Dict with:
            - results: Per-molecule records ``{id, smiles, canonical_smiles,
              passed, num_alerts, alerts: [{source, category, description}]}``.
              ``alerts[].description`` is the exclusion reason.
            - passed: Keep-list — ids of compounds with zero alerts.
            - flagged: Exclude-list — ids of compounds with >= 1 alert.
            - errors: ``{id, smiles}`` for compounds whose SMILES could not be parsed.
            - summary: ``{total, passed, flagged, invalid, by_source}``.
            - count: Number of valid molecules screened.
            - params_used: The parameters that were applied.
        On a schema-level problem (bad/missing fields, duplicate id, unknown
        catalog, empty input) returns the same shape with a top-level ``error``.
    """
    params = params or {}
    # The platform auto-injects `smiles_list_key` = the input_schema array
    # property ("compounds") and delivers the parsed list under input_data[that
    # key]. Honour it; default to "compounds" for direct/CLI calls.
    list_key = params.get("smiles_list_key", "compounds")
    if isinstance(input_data, list):
        raw_list = input_data
    elif isinstance(input_data, dict):
        raw_list = input_data.get(list_key)
        if not isinstance(raw_list, list):
            # Paste mode delivers the list under params[list_key]; in upload
            # mode params[list_key] is a file descriptor (dict) — never treat
            # that as the compound list.
            paste = params.get(list_key)
            raw_list = paste if isinstance(paste, list) else []
    else:
        raw_list = []

    requested = params.get("filter_catalogs", DEFAULT_CATALOGS)
    catalog_names, unknown = _resolve_catalogs(requested)
    if unknown:
        return _error_result(
            f"Unknown filter catalog(s): {unknown}. Allowed: {sorted(CATALOG_NAMES)}", params
        )
    if not catalog_names:
        return _error_result("No alert filter catalogs selected", params)

    if not raw_list:
        return _error_result("No compounds provided", params)

    compounds, validation_error = _validate_compounds(raw_list)
    if validation_error is not None:
        return _error_result(validation_error, params)

    use_reactive = params.get("reactive_smarts", True)
    include_passing = params.get("include_passing", True)

    catalog = _build_catalog(tuple(catalog_names))
    reactive = _REACTIVE_SMARTS if use_reactive else []

    results: list[dict] = []
    passed: list[str] = []
    flagged: list[str] = []
    errors: list[dict] = []
    by_source: dict[str, int] = {}

    for smi, cid in compounds:
        mol = smiles_to_mol(smi)
        if mol is None:
            errors.append({"id": cid, "smiles": smi})
            continue

        alerts = screen_molecule(mol, catalog, reactive)

        record = {
            "id": cid,
            "smiles": smi,
            "canonical_smiles": Chem.MolToSmiles(mol),
            "passed": not alerts,
            "num_alerts": len(alerts),
            "alerts": alerts,
        }

        if alerts:
            flagged.append(cid)
            for alert in alerts:
                by_source[alert["source"]] = by_source.get(alert["source"], 0) + 1
        else:
            passed.append(cid)

        if alerts or include_passing:
            results.append(record)

    summary = {
        "total": len(raw_list),
        "passed": len(passed),
        "flagged": len(flagged),
        "invalid": len(errors),
        "by_source": by_source,
    }

    return {
        "results": results,
        "passed": passed,
        "flagged": flagged,
        "errors": errors,
        "summary": summary,
        "count": len(passed) + len(flagged),
        "params_used": params,
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Structure Alerts — PAINS & reactive-group screening (RDKit)"
    )
    parser.add_argument(
        "--input",
        default=os.environ.get("INPUT_FILE", "input.json"),
        help="Input JSON file with SMILES (default: input.json)",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("OUTPUT_FILE", "output.json"),
        help="Output JSON file (default: output.json)",
    )
    parser.add_argument(
        "--params",
        default=os.environ.get("PARAMS_FILE", "params.json"),
        help="Parameters JSON file (default: params.json)",
    )
    args = parser.parse_args()

    with open(args.input) as f:
        input_data = json.load(f)

    params = {}
    if os.path.exists(args.params):
        with open(args.params) as f:
            params = json.load(f)

    result = run(input_data, params)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    summary = result.get("summary", {})
    print(
        f"Screened {result['count']} molecules -> {args.output} "
        f"(passed={summary.get('passed', 0)}, flagged={summary.get('flagged', 0)}, "
        f"invalid={summary.get('invalid', 0)})"
    )
    if result.get("errors"):
        print(f"  Invalid ({len(result['errors'])}): {', '.join(str(e) for e in result['errors'])}")


if __name__ == "__main__":
    main()
