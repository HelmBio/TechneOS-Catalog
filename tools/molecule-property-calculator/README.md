# Molecule Property Calculator

RDKit-powered molecular property calculator from SMILES strings.

## Properties Calculated

| Property | RDKit Method |
|---|---|
| **MW** | `Descriptors.MolWt` |
| **LogP** | `Descriptors.MolLogP` (Wildman-Crippen) |
| **HBD** | `Lipinski.NumHDonors` |
| **HBA** | `Lipinski.NumHAcceptors` |
| **TPSA** | `Descriptors.TPSA` |
| **Rotatable Bonds** | `Lipinski.NumRotatableBonds` |
| **Heavy Atom Count** | `Lipinski.HeavyAtomCount` |
| **Aromatic Rings** | `Lipinski.NumAromaticRings` |
| **Aliphatic Rings** | `Lipinski.NumAliphaticRings` |
| **Fraction sp3** | `CalcFractionCsp3` |
| **Ring Count** | `CalcNumRings` |
| **Heteroatoms** | `CalcNumHeteroatoms` |
| **Formula** | `CalcMolFormula` |
| **Canonical SMILES** | `MolToSmiles` |

## Requirements

- Python 3.10+
- [RDKit](https://rdkit.org/) (`rdkit` package)

```bash
pip install rdkit
```

## Usage

### Library

```python
from tool import run

# Plain SMILES strings
result = run({"smiles": ["CCO", "c1ccccc1"]}, {"detailed": True})

# With optional ids for tracking
result = run({"smiles": [
    {"smiles": "CCO", "id": "ethanol"},
    {"smiles": "c1ccccc1", "id": "benzene"},
]})

for mol in result["results"]:
    label = mol.get("id", mol["smiles"])
    print(f"{label}: MW={mol['mw']}, LogP={mol['logp']}")
```

### CLI

```bash
# Plain SMILES strings
echo '{"smiles": ["CCO", "c1ccccc1"]}' > input.json
python tool.py

# With ids
echo '{"smiles": [{"smiles": "CCO", "id": "ethanol"}, {"smiles": "c1ccccc1", "id": "benzene"}]}' > input.json
python tool.py
cat output.json
```

### Custom file paths

```bash
python tool.py --input my_molecules.json --output results.json --params options.json
```

## Testing

```bash
python test.py -v
```

## Input Schema

Each entry in `smiles` can be a plain SMILES string or an object with an optional `id`:

```json
{
  "smiles": [
    "CCO",
    {"smiles": "c1ccccc1", "id": "benzene"},
    {"smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C", "id": "caffeine"}
  ]
}
```

### Optional Parameters

```json
{"detailed": true}
```

- `detailed` (bool): Include `num_atoms` and `num_bonds` per molecule (default: false)

## Output Schema

```json
{
  "results": [
    {
      "id": "ethanol",
      "smiles": "CCO",
      "valid": true,
      "mw": 46.069,
      "logp": -0.14,
      "hbd": 1,
      "hba": 1,
      "tpsa": 20.23,
      "rotatable_bonds": 1,
      "heavy_atom_count": 3,
      "aromatic_rings": 0,
      "aliphatic_rings": 0,
      "fraction_sp3": 1.0,
      "num_rings": 0,
      "num_heteroatoms": 1,
      "num_saturated_rings": 0,
      "canonical_smiles": "CCO",
      "formula": "C2H6O"
    }
  ],
  "errors": [],
  "count": 1,
  "params_used": {}
}
```

The `id` field is only present in results when the corresponding input entry included an `id`. Invalid entries in `errors` preserve their original structure (plain string or object).

## Registration as Module Tool

This tool is designed to be registered in the platform as a `module`-type tool:

- **`tool.py`** → `script_content`
- **`test.py`** → `test_script`
- **`script_environment`** → `{"language": "python", "version": "3.12", "dependencies": {"pip": ["rdkit"]}}`

## Limitations

- Computes 2D descriptors only (no 3D geometry or conformers)
- Single-molecule SMILES parsing; does not handle multi-molecule SDF or mol2 files
