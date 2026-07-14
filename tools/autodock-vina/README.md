# AutoDock Vina

Dock a set of **representative molecules** — e.g. the keep-list that survived
[`structure-alerts`](../structure-alerts/) triage and was reduced to one
representative per family by [`compound-clustering`](../compound-clustering/) —
into a **protein receptor** with [AutoDock Vina](https://vina.scripps.edu/), and
rank them by **predicted binding affinity**. This answers the structure-based
question those upstream tools set up: *which chemotypes actually engage the
target, and how strongly?*

Everything is delegated to open-source tooling — RDKit + Meeko for ligand prep,
OpenBabel for receptor prep, and the AutoDock Vina binary for docking — rather
than re-implementing 3D embedding, atom typing, or scoring by hand.

## How it works

| Stage | What happens | Library |
|---|---|---|
| Receptor prep | Strip waters/heteroatoms → add hydrogens + Gasteiger charges → rigid receptor PDBQT | OpenBabel (`obabel -xr`) |
| Ligand prep | SMILES → 3D conformer (ETKDG) → MMFF minimise → ligand PDBQT with rotatable-bond torsion tree | RDKit + Meeko |
| Box | Explicit `center_*`/`size_*`, or derived from a reference ligand (`box_from_ref`) | — |
| Docking | Search the box, return up to `num_modes` poses with affinities (kcal/mol) | AutoDock Vina |
| Ranking | Sort molecules by best (most negative) affinity | — |

The receptor is prepped **once** per run and reused for every ligand. A ligand
that can't be parsed, embedded, or docked is recorded in `errors` and never
fails the batch — the same convention as the other catalog tools.

## Requirements

This is a **container tool**. It builds on the shared `techneos/tool-runtime` base
and installs everything it needs in its own image: the native binaries (`vina`,
`obabel`) via apt, and the Python deps (RDKit, Meeko, SciPy, matplotlib) from
`pyproject.toml`. You do not need Vina installed on the host.

## Input

- **Ligands** — `{"smiles", "id"}` objects, both fields required, ids unique
  (a bare JSON array, a `{"smiles": [...]}` object, or a CSV/TSV with
  `smiles`/`id` columns — the platform's `smiles_list` shapes). See
  [examples/input.json](examples/input.json).
- **Receptor** — a protein **PDB** file. On the platform it's uploaded/selected
  and handed to the tool as `receptor_file`; on the CLI it's `--receptor`.

## Usage

### Docker (no host install of vina/obabel/rdkit)

```bash
./examples/run-in-docker.sh                              # dock the bundled example
./examples/run-in-docker.sh -l ligands.json -r rec.pdb  # your own inputs
./examples/run-in-docker.sh -p params.json -o results   # custom params / output dir
```

Runs the tool through its container exactly as the platform worker does, stages
the inputs, and prints the ranked affinities. Requires the image — build it with
`uv run python packages/tool-runtime/build_and_register.py --skip-register` then
`docker build -t techneos/autodock-vina tools/autodock-vina`.

### CLI

```bash
python -m autodock_vina.docking \
  --input examples/input.json \
  --receptor examples/receptor.pdb \
  --params examples/params.json \
  --output out.json
# writes out.json, plus <id>_poses.sdf and scores.png when those params are set
```

### Library

```python
from autodock_vina.docking import run

result = run(
    {"compounds": [{"smiles": "CC(=O)Oc1ccccc1C(=O)O", "id": "aspirin"}],
     "receptor_file": "examples/receptor.pdb"},
    {"search_box": {"center_x": 10.6, "center_y": 10.2, "center_z": 6.1,
                    "size_x": 24, "size_y": 24, "size_z": 24},
     "exhaustiveness": 8},
)
for r in result["results"]:
    print(r["rank"], r["id"], r["affinity"], "kcal/mol")
```

## Parameters

All search-box settings live under a single **`search_box`** object (omit it
entirely to dock a default-size box centered on the receptor):

| `search_box.*` | Type | Default | Description |
|---|---|---|---|
| `center_x` / `center_y` / `center_z` | number | receptor centroid | Box center (Å). Defaults to the receptor's center when not all three are given. |
| `size_x` / `size_y` / `size_z` | number | `20` | Box dimensions (Å). |
| `box_from_ref` | bool | `false` | Derive box from a reference ligand instead of center/size. |
| `reference_ligand` | str | — | Reference ligand structure (PDB/PDBQT) for `box_from_ref`. |
| `ref_padding` | number | `4.0` | Padding (Å) around the reference bounding box. |

| Param | Type | Default | Description |
|---|---|---|---|
| `exhaustiveness` | int | `8` | Search effort — higher is more thorough but slower (16–32 for production). |
| `num_modes` | int | `9` | Max poses returned per ligand. |
| `energy_range` | number | `3.0` | Max kcal/mol between best and worst returned pose. |
| `seed` | int | `0` | Random seed for reproducibility. |
| `ph` | number | `7.4` | pH for hydrogen addition during prep. |
| `remove_waters` | bool | `true` | Strip crystallographic waters from the receptor. |
| `remove_hetero` | bool | `false` | Strip **all** heteroatoms (cofactors/ions/ligands), not just waters. |
| `write_poses` | bool | `false` | Write each ligand's docked poses to `<id>_poses.sdf`. |
| `render_scores` | bool | `false` | Render a best-affinity bar chart to `scores.png`. |

## Output

```json
{
  "results": [
    {"id": "ibuprofen", "smiles": "...", "affinity": -6.8, "rank": 1,
     "num_poses": 9, "pose_affinities": [-6.8, -6.5, -6.2], "pose_file": "ibuprofen_poses.sdf"}
  ],
  "ranking": ["ibuprofen", "aspirin", "..."],
  "errors": [{"id": "bad-1", "smiles": "not_a_smiles", "reason": "unparseable SMILES"}],
  "summary": {"total": 5, "docked": 5, "failed": 0,
              "best_id": "ibuprofen", "best_affinity": -6.8,
              "box": {"center": [10.6, 10.2, 6.1], "size": [24, 24, 24]},
              "vina_version": "AutoDock Vina v1.2.x"},
  "count": 5,
  "params_used": {"...": "..."},
  "images": {"scores": "scores.png"}
}
```

- `affinity` is the **best** (most negative) pose's predicted binding free
  energy in **kcal/mol** — more negative = stronger predicted binding.
- `results` and `ranking` are ordered **strongest binder first**.
- On the platform, pose SDFs and `scores.png` land in the run's output folder
  (collected via `techneos-tool-runtime`); the CLI writes them next to `--output`.

## Testing

```bash
uv sync
uv run pytest -q
# or standalone, no pytest:
python tests/test_docking.py -v
```

Unit tests cover input parsing, box resolution, affinity parsing, and ranking
without needing the Vina binary. The real-docking smoke test
(`tests/test_container_smoke.py`) builds the image and docks through the
container entrypoint; it skips cleanly when Docker or the base image is absent.

## Limitations

- **Rigid-receptor** docking — no flexible side chains, ensemble docking, or
  induced fit. Receptor prep is a lightweight OpenBabel pass, not full
  protonation-state optimisation; supply a pre-prepared receptor upstream if you
  need that level of care.
- One 3D conformer per ligand (ETKDG + MMFF); no explicit tautomer/stereo
  enumeration — provide the protonation/tautomer/stereo you want in the SMILES.
- Vina affinities are an empirical scoring function: good for **ranking** and
  triage, not a substitute for experimental binding measurement.
- Define the box around the known binding site for meaningful results; a box
  spanning the whole protein (blind docking) is slower and noisier.
