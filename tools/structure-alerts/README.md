# Structure Alerts

Screen compounds — e.g. the hit list from an **HTS campaign** — for **PAINS**
(pan-assay-interference) substructures and **reactive / unstable functional
groups**, and get the *specific reason* each compound is flagged.

Matching is delegated to RDKit's built-in
[`FilterCatalog`](https://www.rdkit.org/docs/source/rdkit.Chem.rdfiltercatalog.html),
the literature-reference SMARTS encodings of the published alert sets, plus a
small curated reactive-group SMARTS list on top. We do **not** re-derive these
patterns by hand.

## Alert sets (selectable at runtime)

| Name | Source | Covers |
|---|---|---|
| `PAINS` (`PAINS_A`/`PAINS_B`/`PAINS_C`) | Baell & Holloway | Pan-assay interference / frequent hitters |
| `BRENK` | Brenk et al. | Reactive, toxic, metabolically unstable groups |
| `NIH` | NIH MLSMR | Excluded functionality / reactivity |
| `ZINC` | ZINC | Drug-like / reactivity rules |
| `CHEMBL` | ChEMBL (Dundee, BMS, Glaxo, Inpharmatica, LINT, MLSMR, SureChEMBL) | Medchem liability rules |
| `ALL` | — | Every set above |
| `reactive_smarts` | curated here | Acyl/sulfonyl halides, Michael acceptors, epoxides, aldehydes, isocyanates, anhydrides, etc. |

Default: `["PAINS", "BRENK"]` + the reactive-group SMARTS list.

## Why RDKit (not from scratch)

RDKit is already the platform's chemistry dependency, and its `FilterCatalog`
ships the canonical published alert SMARTS — thousands of curated patterns — with
a ready-made human-readable description per match. Matching is a fast compiled
substructure search. Building and maintaining these SMARTS by hand would
re-derive the literature and inevitably drift from the reference sets.

## Requirements

- Python 3.12
- [RDKit](https://rdkit.org/) (`rdkit`)

## Input

Compounds are `{"smiles", "id"}` objects — both fields required, ids unique.

When run on the platform, the uploaded file is parsed into this list and handed
to the tool. Upload one of the shapes the platform's `smiles_list` parser
understands — a **bare JSON array** (see [examples/input.json](examples/input.json)),
a `{"smiles": [...]}` object, or a CSV/TSV with `smiles`/`id` columns:

```json
[
  {"smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "id": "caffeine"},
  {"smiles": "Oc1ccccc1O", "id": "catechol"}
]
```

## Usage

### Library

```python
from structure_alerts.checker import run

# input may be the list directly, or a dict keyed by the array property
result = run(
    [
        {"smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "id": "caffeine"},
        {"smiles": "Oc1ccccc1O", "id": "catechol"},
        {"smiles": "CC(=O)Cl", "id": "acetyl-chloride"},
    ],
    {"filter_catalogs": ["PAINS", "BRENK"], "reactive_smarts": True},
)

print("keep:   ", result["passed"])    # ['caffeine']
print("exclude:", result["flagged"])   # ['catechol', 'acetyl-chloride']
for rec in result["results"]:
    if not rec["passed"]:
        reasons = ", ".join(f"{a['source']}:{a['description']}" for a in rec["alerts"])
        print(f"  {rec['id']}: {reasons}")
```

### CLI

```bash
python -m structure_alerts.checker \
  --input examples/input.json \
  --params examples/params.json \
  --output output.json
```

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `filter_catalogs` | list[str] | `["PAINS", "BRENK"]` | RDKit filter catalogs (alert sets) to apply (case-insensitive). `["ALL"]` enables every set. |
| `reactive_smarts` | bool | `true` | Also apply the curated reactive-group SMARTS list. |
| `include_passing` | bool | `true` | Include clean compounds in `results` (the `passed` list is always populated). |

> The platform auto-injects `smiles_list_key` (the input_schema array property,
> `compounds`) so the tool reads the list from the right key — you don't set it.

## Output

```json
{
  "results": [
    {
      "id": "catechol",
      "smiles": "Oc1ccccc1O",
      "canonical_smiles": "Oc1ccccc1O",
      "passed": false,
      "num_alerts": 2,
      "alerts": [
        {"source": "PAINS_B", "category": "pains", "description": "catechol_A(92)"},
        {"source": "Brenk", "category": "reactive", "description": "catechol"}
      ]
    }
  ],
  "passed":  ["caffeine"],
  "flagged": ["catechol", "acetyl-chloride"],
  "errors":  [{"id": "invalid-1", "smiles": "not_a_smiles"}],
  "summary": {"total": 4, "passed": 1, "flagged": 2, "invalid": 1, "by_source": {"PAINS_B": 1, "Brenk": 2, "reactive_smarts": 1}},
  "count": 3,
  "params_used": {"filter_catalogs": ["PAINS", "BRENK"]}
}
```

- `passed` is the **keep-list**, `flagged` is the **exclude-list**.
- `alerts[].description` is the per-compound exclusion reason.
- This tool annotates rather than destroys — the caller decides whether to drop
  flagged compounds or keep them with their reasons.

## Testing

```bash
uv sync
uv run pytest -q
# or standalone, no pytest:
python tests/test_checker.py -v
```

## Limitations

- 2D substructure matching only (no 3D / tautomer enumeration).
- Single-molecule SMILES; does not parse multi-component SDF/mol2.
- Alerts are heuristics — a flag is a triage signal, not a verdict. The ChEMBL
  and "ALL" sets are aggressive and will flag many drug-like cores.
