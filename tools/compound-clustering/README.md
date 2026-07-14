# Compound Clustering

Group a list of compounds — e.g. the **keep-list** that survived
[`structure-alerts`](../structure-alerts/) triage — into **distinct chemical
families**, for diversity selection, representative picking, and understanding the
chemical space of a hit set.

Three methods are selectable at runtime:

| `method` | What it does | Library |
|---|---|---|
| `butina` (default) | Morgan/ECFP fingerprints + Tanimoto distance, clustered with the Taylor–Butina algorithm. **Auto-discovers** the number of families from a distance `cutoff` — no fixed *k*. Each cluster's first member is its centroid. | `rdkit.ML.Cluster.Butina` |
| `scaffold` | Reduce each molecule to its **Bemis–Murcko scaffold**; compounds sharing a canonical ring-system core form one family. Most interpretable — each cluster carries its `scaffold_smiles`. | `rdkit.Chem.Scaffolds.MurckoScaffold` |
| `kmeans` | Fingerprint bit-vectors clustered with **k-means** at a user-specified `n_clusters`; representative = member nearest the centroid. | `scikit-learn` |

## Why RDKit + scikit-learn (not from scratch)

RDKit is already the platform's chemistry dependency and ships the canonical,
literature-standard building blocks — Morgan/ECFP & MACCS fingerprints, Tanimoto
similarity, the Taylor–Butina clusterer, and Bemis–Murcko scaffold extraction.
scikit-learn provides a battle-tested k-means. Re-implementing fingerprints or
clustering by hand would re-derive well-trodden code and inevitably drift.

## Requirements

- Python 3.12
- [RDKit](https://rdkit.org/) (`rdkit`)
- [scikit-learn](https://scikit-learn.org/) + [numpy](https://numpy.org/) (k-means)
- [matplotlib](https://matplotlib.org/) (optional chemical-space plot; also provides
  Pillow, which RDKit uses to draw the structure grid)

## Input

Compounds are `{"smiles", "id"}` objects — both fields required, ids unique.

When run on the platform, the uploaded file is parsed into this list and handed to the
tool. Upload one of the shapes the platform's `smiles_list` parser understands — a
**bare JSON array** (see [examples/input.json](examples/input.json)), a
`{"smiles": [...]}` object, or a CSV/TSV with `smiles`/`id` columns:

```json
[
  {"smiles": "CC(=O)Oc1ccccc1C(=O)O", "id": "aspirin"},
  {"smiles": "Nc1ccc(cc1)S(=O)(=O)N", "id": "sulfanilamide"}
]
```

## Usage

### Library

```python
from compound_clustering.clustering import run

# input may be the list directly, or a dict keyed by the array property
result = run(
    [
        {"smiles": "CC(=O)Oc1ccccc1C(=O)O", "id": "aspirin"},
        {"smiles": "CC(=O)Oc1ccccc1C(=O)OC", "id": "methyl-acetylsalicylate"},
        {"smiles": "Nc1ccc(cc1)S(=O)(=O)N", "id": "sulfanilamide"},
        {"smiles": "OCC1OC(O)C(O)C(O)C1O", "id": "glucose"},
    ],
    {"method": "butina", "cutoff": 0.35},
)

for cluster in result["clusters"]:
    print(f"family {cluster['cluster_id']} (rep {cluster['representative_id']}): "
          f"{cluster['member_ids']}")
```

### CLI

```bash
python -m compound_clustering.clustering \
  --input examples/input.json \
  --params examples/params.json \
  --output output.json
```

## Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `method` | str | `"butina"` | `butina`, `scaffold`, or `kmeans`. |
| `fingerprint` | str | `"morgan"` | `morgan`, `ecfp4`, `ecfp6`, `maccs` (butina / kmeans). |
| `radius` | int | `2` | Morgan radius (ignored for ecfp4/ecfp6/maccs). |
| `n_bits` | int | `2048` | Morgan fingerprint length. |
| `cutoff` | float | `0.35` | Butina Tanimoto **distance** threshold (`0.35` distance ≈ `0.65` similarity). |
| `n_clusters` | int | `5` | Number of clusters for `kmeans` (capped at #compounds). |
| `generic_scaffold` | bool | `false` | `scaffold` only: reduce to the generic ring skeleton before grouping. |
| `render_grid` | bool | `false` | Also write a per-cluster 2D structure grid to `clusters.png` in the output folder. |
| `render_chemical_space` | bool | `false` | Also write a PCA scatter of Morgan fingerprints, colored by cluster, to `chemical_space.png` (needs ≥ 3 valid molecules). |

> The platform auto-injects `smiles_list_key` (the input_schema array property,
> `compounds`) so the tool reads the list from the right key — you don't set it.

## Output

```json
{
  "results": [
    {"id": "aspirin", "smiles": "CC(=O)Oc1ccccc1C(=O)O", "canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O", "cluster": 1, "is_representative": true}
  ],
  "clusters": [
    {"cluster_id": 1, "size": 3, "representative_id": "aspirin", "member_ids": ["aspirin", "methyl-acetylsalicylate", "propanoyl-salicylate"]}
  ],
  "errors": [{"id": "invalid-1", "smiles": "not_a_smiles"}],
  "summary": {"total": 11, "num_clusters": 4, "num_singletons": 1, "largest_cluster_size": 3, "invalid": 1, "method": "butina"},
  "count": 10,
  "params_used": {"method": "butina", "cutoff": 0.35}
}
```

- Clusters are ordered **largest-first**; `cluster` ids are 1-based.
- `is_representative` marks one compound per cluster (Butina centroid, the
  member nearest the k-means centroid, or the first scaffold member).
- Singletons are real lone chemotypes — the `summary.num_singletons` count is a
  quick diversity signal.

## Visualization

Set `render_grid` and/or `render_chemical_space` to also emit PNGs into the output
folder (no separate step needed):

| File | Param | What it shows |
|---|---|---|
| `clusters.png` | `render_grid` | 2D structures laid out by family, each labelled `id [fam N]`, with the family representative starred (★). The "show me each family's molecules" view. |
| `chemical_space.png` | `render_chemical_space` | A 2D PCA of Morgan fingerprints, one point per compound, colored by cluster — the chemical-space "map". Needs ≥ 3 valid molecules. |

```bash
python -m compound_clustering.clustering \
  --input examples/input.json \
  --params <(echo '{"method":"butina","cutoff":0.45,"render_grid":true,"render_chemical_space":true}') \
  --output out.json
# writes out.json, clusters.png, chemical_space.png alongside each other
```

On the platform the images land in the run's output folder (collected via
`techneos-tool-runtime`); the CLI writes them next to `--output`. When a render is
requested the result carries an `images` field, e.g.
`{"grid": "clusters.png", "chemical_space": "chemical_space.png"}` — or
`{"chemical_space_error": "..."}` if a render was skipped (rendering never fails the
clustering itself).

> For large sets PCA crowds; swap in t-SNE/UMAP downstream for cleaner separation.

## Testing

```bash
uv sync
uv run pytest -q
# or standalone, no pytest:
python tests/test_clustering.py -v
```

## Limitations

- 2D fingerprints / scaffolds only (no 3D, conformers, or tautomer enumeration).
- Single-molecule SMILES; does not parse multi-component SDF/mol2.
- `butina` results depend on `cutoff` and the chosen fingerprint; `kmeans` needs a
  sensible `n_clusters`. Clustering is a guide to chemical space, not a verdict.
- Acyclic molecules reduce to an empty Bemis–Murcko scaffold and share one family
  under the `scaffold` method.
