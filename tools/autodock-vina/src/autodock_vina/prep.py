"""Structure preparation for docking — ligands and receptor → PDBQT.

AutoDock Vina reads both the receptor and each ligand as **PDBQT** (PDB plus
partial charges ``Q`` and AutoDock atom types ``T``). This module turns the
tool's two raw inputs into that format:

- **Ligands**: a SMILES string → a 3D, hydrogen-added conformer (RDKit ETKDG +
  MMFF) → a PDBQT with a correct rotatable-bond torsion tree (Meeko). Meeko is
  the reference ligand-prep for Vina; OpenBabel (``obabel --gen3d``) is the
  fallback when Meeko isn't importable.
- **Receptor**: a raw PDB → waters/heteroatoms stripped → hydrogens added and
  Gasteiger charges assigned, written as a *rigid* receptor PDBQT (OpenBabel
  ``-xr``). This is the classic lightweight prep; it intentionally does not do
  full protonation-state optimisation (provide a pre-prepared receptor upstream
  if you need that).

All heavy imports (``rdkit``, ``meeko``) are deferred into the functions so the
module imports cleanly in environments that only exercise the pure logic.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Residue names treated as crystallographic water and always dropped.
WATER_RESNAMES = {"HOH", "WAT", "DOD", "H2O", "TIP", "TIP3", "SOL"}


class PrepError(Exception):
    """Raised when a ligand or receptor cannot be prepared for docking."""


# ── Ligands ──────────────────────────────────────────────────────────────────


def smiles_to_mol3d(smiles: str, seed: int = 0):
    """SMILES → an RDKit Mol with explicit Hs and a single 3D conformer.

    Embeds with ETKDGv3 and minimises with MMFF (UFF fallback). Returns the Mol
    or raises :class:`PrepError` with the reason (unparseable SMILES, embedding
    failure, …) so the caller can record it per-compound and carry on.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem
    except ImportError as exc:  # pragma: no cover - exercised only without rdkit
        raise PrepError(f"RDKit is required for ligand prep: {exc}") from exc

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise PrepError("unparseable SMILES")
    mol = Chem.AddHs(mol)

    params = AllChem.ETKDGv3()
    params.randomSeed = int(seed)
    if AllChem.EmbedMolecule(mol, params) != 0:
        # Retry with random coordinates — helps strained/cage-like molecules.
        params.useRandomCoords = True
        if AllChem.EmbedMolecule(mol, params) != 0:
            raise PrepError("3D embedding failed")

    try:
        if AllChem.MMFFOptimizeMolecule(mol) != 0:
            AllChem.UFFOptimizeMolecule(mol)
    except Exception:  # noqa: BLE001 - minimisation is best-effort
        try:
            AllChem.UFFOptimizeMolecule(mol)
        except Exception:  # noqa: BLE001
            pass
    return mol


def _ligand_pdbqt_meeko(mol) -> str | None:
    """Write a ligand PDBQT string with Meeko, or None if Meeko is unavailable.

    Handles both the modern Meeko API (``prepare`` returns molecule setups +
    ``PDBQTWriterLegacy``) and the legacy ``write_pdbqt_string`` API.
    """
    try:
        from meeko import MoleculePreparation
    except ImportError:
        return None

    prep = MoleculePreparation()
    setups = prep.prepare(mol)

    # Modern API: prepare() -> list of setups, written via PDBQTWriterLegacy.
    if setups:
        try:
            from meeko import PDBQTWriterLegacy

            pdbqt, ok, err = PDBQTWriterLegacy.write_string(setups[0])
            if ok:
                return pdbqt
            raise PrepError(f"Meeko PDBQT write failed: {err}")
        except ImportError:
            pass

    # Legacy API: prepare() mutates the preparator; string read off it.
    writer = getattr(prep, "write_pdbqt_string", None)
    if callable(writer):
        return writer()
    raise PrepError("Meeko produced no ligand setup")


def _ligand_pdbqt_obabel(smiles: str, ph: float, out_path: Path) -> None:
    """Fallback ligand prep with OpenBabel: SMILES → 3D → PDBQT."""
    obabel = shutil.which("obabel")
    if obabel is None:
        raise PrepError("neither Meeko nor OpenBabel is available for ligand prep")
    cmd = [
        obabel,
        f"-:{smiles}",
        "--gen3d",
        "-p",
        str(ph),
        "--partialcharge",
        "gasteiger",
        "-O",
        str(out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise PrepError(f"OpenBabel ligand prep failed: {proc.stderr.strip()[:200]}")


def prepare_ligand(smiles: str, out_path: Path, seed: int = 0, ph: float = 7.4) -> Path:
    """Prepare one ligand PDBQT from a SMILES string.

    Primary path: RDKit 3D embed + Meeko PDBQT. Falls back to OpenBabel's own
    ``--gen3d`` pipeline when Meeko isn't importable. Raises :class:`PrepError`
    on any failure (the caller records it per-compound).
    """
    out_path = Path(out_path)
    try:
        mol = smiles_to_mol3d(smiles, seed=seed)
        pdbqt = _ligand_pdbqt_meeko(mol)
        if pdbqt is not None:
            out_path.write_text(pdbqt)
            return out_path
    except PrepError:
        raise
    except Exception:  # noqa: BLE001 - RDKit/Meeko blew up; try obabel before giving up
        pass
    # Meeko unavailable (returned None) or the RDKit path failed unexpectedly.
    _ligand_pdbqt_obabel(smiles, ph=ph, out_path=out_path)
    return out_path


# ── Receptor ─────────────────────────────────────────────────────────────────


def clean_pdb(
    pdb_path: Path,
    out_path: Path,
    remove_waters: bool = True,
    remove_hetero: bool = False,
) -> Path:
    """Strip waters (and optionally all heteroatoms) from a PDB file.

    Keeps ``ATOM`` records; drops ``HETATM`` waters always when
    ``remove_waters`` is set, and all ``HETATM`` when ``remove_hetero`` is set
    (e.g. to discard cofactors/ions before docking). Other records pass through.
    """
    pdb_path = Path(pdb_path)
    out_lines: list[str] = []
    for line in pdb_path.read_text().splitlines():
        rec = line[:6].strip()
        if rec == "HETATM":
            resname = line[17:20].strip().upper()
            if remove_hetero:
                continue
            if remove_waters and resname in WATER_RESNAMES:
                continue
        out_lines.append(line)
    out_path = Path(out_path)
    out_path.write_text("\n".join(out_lines) + "\n")
    return out_path


def prepare_receptor(
    pdb_path: Path,
    out_pdbqt: Path,
    remove_waters: bool = True,
    remove_hetero: bool = False,
    ph: float = 7.4,
) -> Path:
    """Prepare a rigid receptor PDBQT from a raw PDB.

    Cleans the PDB (waters/heteroatoms), then uses OpenBabel to add hydrogens at
    ``ph``, assign Gasteiger charges, and emit a rigid receptor PDBQT (``-xr``,
    no torsion tree). Raises :class:`PrepError` if OpenBabel is missing or fails.
    """
    obabel = shutil.which("obabel")
    if obabel is None:
        raise PrepError("OpenBabel (obabel) is required for receptor prep")

    out_pdbqt = Path(out_pdbqt)
    cleaned = out_pdbqt.with_suffix(".clean.pdb")
    clean_pdb(pdb_path, cleaned, remove_waters=remove_waters, remove_hetero=remove_hetero)

    cmd = [
        obabel,
        str(cleaned),
        "-O",
        str(out_pdbqt),
        "-p",
        str(ph),
        "--partialcharge",
        "gasteiger",
        "-xr",  # rigid receptor: no ROOT/BRANCH torsion tree
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_pdbqt.exists() or out_pdbqt.stat().st_size == 0:
        raise PrepError(f"OpenBabel receptor prep failed: {proc.stderr.strip()[:200]}")
    return out_pdbqt


# ── Search box ───────────────────────────────────────────────────────────────


def _atom_coords(path: Path) -> tuple[list[float], list[float], list[float]]:
    """Collect ATOM/HETATM x/y/z columns from a PDB/PDBQT file."""
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for line in Path(path).read_text().splitlines():
        if line[:6].strip() in ("ATOM", "HETATM"):
            try:
                xs.append(float(line[30:38]))
                ys.append(float(line[38:46]))
                zs.append(float(line[46:54]))
            except ValueError:
                continue
    return xs, ys, zs


def receptor_center(pdb_path: Path) -> list[float]:
    """Bounding-box center of a receptor's atoms — the default docking-box center.

    Used when the caller doesn't specify a box center: a default-size box placed
    here sits over the middle of the structure. Returns ``[x, y, z]`` in Ångström.
    """
    xs, ys, zs = _atom_coords(pdb_path)
    if not xs:
        raise PrepError(f"no atom coordinates found in receptor {Path(pdb_path).name}")
    return [
        (min(xs) + max(xs)) / 2.0,
        (min(ys) + max(ys)) / 2.0,
        (min(zs) + max(zs)) / 2.0,
    ]


def box_from_reference(ref_path: Path, padding: float = 4.0) -> tuple[list[float], list[float]]:
    """Derive a docking box (center, size) from a reference ligand structure.

    Reads ATOM/HETATM coordinates from a PDB/PDBQT reference ligand, returns the
    bounding-box center and (extent + 2*padding) size, both as ``[x, y, z]`` in
    Ångström. Useful to target a known binding site without hand-measuring it.
    """
    ref_path = Path(ref_path)
    xs, ys, zs = _atom_coords(ref_path)
    if not xs:
        raise PrepError(f"no atom coordinates found in reference {ref_path.name}")

    center = [
        (min(xs) + max(xs)) / 2.0,
        (min(ys) + max(ys)) / 2.0,
        (min(zs) + max(zs)) / 2.0,
    ]
    size = [
        (max(xs) - min(xs)) + 2 * padding,
        (max(ys) - min(ys)) + 2 * padding,
        (max(zs) - min(zs)) + 2 * padding,
    ]
    return center, size
