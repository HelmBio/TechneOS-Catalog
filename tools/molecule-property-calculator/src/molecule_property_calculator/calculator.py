"""
Molecule Property Calculator

Calculates molecular properties from SMILES strings using RDKit.

Usage (CLI):
    echo '{"smiles": ["CCO", "c1ccccc1"]}' > input.json
    python -m molecule_property_calculator.calculator --input input.json --output output.json

Usage (library):
    from molecule_property_calculator.calculator import run
    result = run({"smiles": ["CCO"]}, {"detailed": True})
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors

PROPERTY_MAP = {
    "mw": ("Molecular Weight", lambda m: Descriptors.MolWt(m)),
    "logp": ("Wildman-Crippen LogP", lambda m: Descriptors.MolLogP(m)),
    "hbd": ("Hydrogen Bond Donors", lambda m: Lipinski.NumHDonors(m)),
    "hba": ("Hydrogen Bond Acceptors", lambda m: Lipinski.NumHAcceptors(m)),
    "tpsa": ("Topological Polar Surface Area", lambda m: Descriptors.TPSA(m)),
    "rotatable_bonds": ("Rotatable Bonds", lambda m: Lipinski.NumRotatableBonds(m)),
    "heavy_atom_count": ("Heavy Atoms", lambda m: Lipinski.HeavyAtomCount(m)),
    "aromatic_rings": ("Aromatic Rings", lambda m: Lipinski.NumAromaticRings(m)),
    "aliphatic_rings": ("Aliphatic Rings", lambda m: Lipinski.NumAliphaticRings(m)),
    "hba_lipinski": ("HBA (Lipinski)", lambda m: Lipinski.NumHAcceptors(m)),
    "hbd_lipinski": ("HBD (Lipinski)", lambda m: Lipinski.NumHDonors(m)),
    "fraction_sp3": ("Fraction sp3", lambda m: rdMolDescriptors.CalcFractionCsp3(m)),
    "num_rings": ("Ring Count", lambda m: rdMolDescriptors.CalcNumRings(m)),
    "num_heteroatoms": ("Heteroatoms", lambda m: rdMolDescriptors.CalcNumHeteroatoms(m)),
    "num_saturated_rings": ("Saturated Rings", lambda m: rdMolDescriptors.CalcNumSaturatedRings(m)),
}


@lru_cache(maxsize=1024)
def smiles_to_mol(smiles: str) -> Chem.Mol | None:
    """Convert SMILES to RDKit Mol object (cached for repeated lookups)."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is not None:
        Chem.SanitizeMol(mol)
    return mol


def _normalize_input_item(item: str | dict) -> tuple[str, str | None]:
    """Normalize a SMILES input item to (smiles, id).

    Accepts either a plain SMILES string or an object ``{"smiles": "...", "id": "..."}``.
    """
    if isinstance(item, dict):
        return item.get("smiles", ""), item.get("id")
    return item, None


def calculate_properties(smiles: str, detailed: bool = False) -> dict | None:
    """Calculate molecular properties for a single SMILES string.

    Returns None if the SMILES is invalid.
    """
    mol = smiles_to_mol(smiles)
    if mol is None:
        return None

    props = {"smiles": smiles, "valid": True}
    for key, (_, func) in PROPERTY_MAP.items():
        try:
            val = func(mol)
            props[key] = round(val, 3) if isinstance(val, float) else val
        except Exception:
            props[key] = None

    props["canonical_smiles"] = Chem.MolToSmiles(mol)
    props["formula"] = rdMolDescriptors.CalcMolFormula(mol)

    if detailed:
        props["num_atoms"] = mol.GetNumAtoms()
        props["num_bonds"] = mol.GetNumBonds()

    return props


def run(input_data: dict, params: dict | None = None) -> dict:
    """Calculate molecular properties for a list of SMILES strings.

    Each entry in ``input_data["smiles"]`` can be either a plain SMILES string
    or an object ``{"smiles": "...", "id": "..."}`` for tracking inputs.

    Args:
        input_data: Dictionary with a key (default ``"smiles"``) mapping to a
            list of SMILES strings or ``{"smiles": str, "id": str}`` objects.
            The key name is configurable via ``params["smiles_list_key"]``.
        params: Optional dictionary with calculation options.
            Supported keys:
                - smiles_list_key (str): Key name in ``input_data`` to read
                  SMILES from (default ``"smiles"``). Allows the caller to
                  pass data under a different key (e.g. ``"compounds"``).
                - detailed (bool): Include extra per-molecule info (default False)

    Returns:
        Dictionary with:
            - results: List of per-molecule property dictionaries (includes
              ``id`` if provided in the input)
            - errors: List of invalid entries (strings or dicts with id)
            - count: Number of successfully processed molecules
            - params_used: The parameters that were applied
    """
    params = params or {}
    smiles_key = params.get("smiles_list_key", "smiles")
    raw_list = input_data.get(smiles_key, []) or params.get(smiles_key, [])

    if not raw_list:
        return {
            "error": "No SMILES provided",
            "results": [],
            "errors": [],
            "count": 0,
            "params_used": params,
        }

    detailed = params.get("detailed", False)
    results = []
    errors = []

    for item in raw_list:
        smi, mol_id = _normalize_input_item(item)
        props = calculate_properties(smi, detailed=detailed)
        if props is None:
            errors.append(item)
        else:
            if mol_id is not None:
                props["id"] = mol_id
            results.append(props)

    return {
        "results": results,
        "errors": errors,
        "count": len(results),
        "params_used": params,
    }


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Molecule Property Calculator (RDKit)")
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

    print(f"Computed properties for {result['count']} molecules -> {args.output}")
    if result.get("errors"):
        print(f"  Errors ({len(result['errors'])}): {', '.join(str(e) for e in result['errors'])}")


if __name__ == "__main__":
    main()
