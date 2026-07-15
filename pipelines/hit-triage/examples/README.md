# Hit Triage — example run (GLP-1 target)

Inputs for an end-to-end hit-triage run docking a small screening library into
the **GLP-1 receptor (GLP-1R)**.

## Files

| File | Used on stop | What it is |
|---|---|---|
| `compounds.json` | `screen_alerts` | 17 `{smiles, id}` candidates — a demonstration screening library. |
| `5VAI_GLP-1R.pdb` | `dock_vina` | GLP-1 receptor structure (RCSB 5VAI, activated GLP-1R–Gs complex). |

### `compounds.json`
A realistic mixed bag so every stage does something:
- ~12 valid, drug-like molecules (incl. **metformin**, an antidiabetic) that
  pass the structure-alerts filter and flow downstream.
- 4 that **structure-alerts flags** and drops: `catechol-pains`,
  `benzoquinone-pains` (PAINS), `acetyl-chloride-reactive`,
  `methyl-vinyl-ketone-michael` (reactive).
- 1 invalid SMILES (`invalid-1`) to show error handling.

> The compounds are a generic candidate set — the run is "against GLP-1"
> because they're docked into the GLP-1R structure, not because they're known
> GLP-1 binders.

### `5VAI_GLP-1R.pdb`
Shipped here already (RCSB 5VAI). To grab a different structure, use the helper
from the repo root — it saves as `{PDB_ID}_{TARGET}.pdb` in this folder:
```bash
./bin/helper/fetch_receptor.sh                 # 5VAI / GLP-1R (default)
./bin/helper/fetch_receptor.sh 6X18 GLP-1R     # small-molecule-agonist-bound GLP-1R
```

## Run it

1. Register the pipeline (and its three tools) if you haven't:
   `uv run python pipelines/hit-triage/register.py --env local --upsert`
2. In the web UI, open **Hit Triage** → run the active version.
3. **Pipeline** stop: optional run name.
   **screen_alerts** stop → Input data → Upload `compounds.json`.
   **dock_vina** stop → Input data → Upload `5VAI_GLP-1R.pdb`.
4. Submit and watch `/pipeline-runs/<id>`.

## Expected flow

- **screen_alerts** keeps the clean compounds, drops the 4 flagged + 1 invalid.
- **cluster_compounds** groups the survivors into chemical families and marks a
  representative per family (fed automatically from `screen_alerts` via the
  declared `compounds <- screen_alerts (passed)` mapping).
- **dock_vina** docks the representatives into GLP-1R and ranks them by
  predicted affinity (fed from `cluster_compounds` representatives).

## Tip: focus the docking box

`fetch_receptor.sh` pulls the whole receptor. For meaningful scores on a 7TM
target, target the pocket via the `dock_vina` step params — set
`search_box.center_{x,y,z}`, or `box_from_ref=true` with the co-crystallised
ligand — rather than the default centroid box.
