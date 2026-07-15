# Hit Triage

An end-to-end **pipeline** that chains three catalog tools into one workflow:
give it a raw screening library and a protein receptor, and it returns a short,
ranked list of docked representative hits.

It mirrors how a computational chemist triages an **HTS / virtual-screening
campaign**: throw out the junk, de-duplicate by chemotype, then dock what's left.

## What it does

| Step | Tool | Does | Produces |
|---|---|---|---|
| `screen_alerts` | `structure-alerts` | Flags PAINS + reactive groups, keeps the clean compounds | keep-list of survivors |
| `cluster_compounds` | `compound-clustering` | Groups survivors into chemical families (Butina / Morgan), picks one representative per family | representatives |
| `dock_vina` | `autodock-vina` | Docks the representatives into the receptor, ranks by predicted binding affinity | affinity ranking |

```
compounds ──▶ screen_alerts ──▶ cluster_compounds ──▶ dock_vina ──▶ ranked hits
receptor ───────────────────────────────────────────▶ (docking)
```

The diagram above is **the pipeline's DAG** — its fixed shape. A pipeline
**version** doesn't redraw this graph; it simply **pins which tool version runs
at each step and the parameter values used**. Open the **Versions** section on
this page and expand a version to see those bindings (tool pins + parameters).
To run, pick the version whose pins you want.

## How to run

1. In the **Versions** section, find the version you want (it lists the tool
   pins and parameters it uses) and click the **Run ▶** button on it.
2. A run dialog opens and walks you through the pipeline and each step. Give the
   run an optional name, provide the two inputs, and adjust any step parameters
   you want to override (the defaults below are used otherwise).
3. Click **Submit**. You'll land on the run page where you can watch each step
   progress and, when `dock_vina` finishes, download the ranked results.

### Inputs

| Input | Goes to | What to provide |
|---|---|---|
| **Compounds** | `screen_alerts` | The library to triage — a list of `{smiles, id}` objects (ids unique). Paste SMILES directly, upload a file, or pick an existing dataset. |
| **Receptor** | `dock_vina` | The target protein structure as a **PDB** file — upload it or select a dataset at run time. |

Only `compounds` and `receptor` are supplied by you. The compounds flowing into
`cluster_compounds` and `dock_vina` are passed automatically from the previous
step, so you don't provide them again.

Example compounds:

```json
[
  { "smiles": "CC(=O)Oc1ccccc1C(=O)O", "id": "aspirin" },
  { "smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O", "id": "ibuprofen" },
  { "smiles": "Oc1ccccc1O", "id": "catechol-pains" }
]
```

### Parameters you can tune

These have sensible defaults; override them in the run dialog only if needed:

- **`screen_alerts`** — `filter_catalogs` (default `PAINS`, `BRENK`),
  `reactive_smarts`, `include_passing`.
- **`cluster_compounds`** — `method` (default `butina`), `fingerprint`
  (default `morgan`), `cutoff` (default `0.35`).
- **`dock_vina`** — `exhaustiveness` (default `8`), `num_modes` (default `9`),
  `render_scores`.

### What you get back

- A **keep-list** of compounds that passed the structure-alert screen.
- **Representatives** — one compound per chemical family after clustering.
- A final **affinity ranking** of the docked representatives, with predicted
  binding scores, available as downloadable artifacts on the run page.
