"""AutoDock Vina subprocess adapter.

Wraps the ``vina`` binary (installed by this tool's Dockerfile on top of
``techneos/tool-runtime``). We invoke
the classic command-line interface — ``--receptor/--ligand`` + the box flags —
which is stable across Vina 1.1.x and 1.2.x, and we read per-pose affinities
from the ``REMARK VINA RESULT:`` lines in the output PDBQT rather than parsing
stdout or a ``--log`` file (``--log`` was removed in Vina 1.2.0).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class VinaError(Exception):
    """Raised when a docking run fails to produce results."""


@dataclass(frozen=True)
class VinaSettings:
    """Search-box and sampling parameters for one Vina run."""

    center: tuple[float, float, float]
    size: tuple[float, float, float]
    exhaustiveness: int = 8
    num_modes: int = 9
    energy_range: float = 3.0
    seed: int = 0
    cpu: int | None = None


def vina_binary() -> str:
    """Return the path to the ``vina`` executable, or raise if it's missing."""
    path = shutil.which("vina")
    if path is None:
        raise VinaError(
            "the `vina` binary is not on PATH — run inside the techneos/autodock-vina image"
        )
    return path


def vina_version() -> str:
    """Best-effort Vina version string (for diagnostics)."""
    try:
        proc = subprocess.run(
            [vina_binary(), "--version"], capture_output=True, text=True, timeout=30
        )
        return (proc.stdout or proc.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "unknown"


def parse_affinities(pdbqt_text: str) -> list[float]:
    """Extract per-pose affinities (kcal/mol) from a docked PDBQT.

    Each docked model carries a line like
    ``REMARK VINA RESULT:    -9.1   0.000   0.000`` — the first number is the
    predicted binding affinity. Returns them in file order (Vina writes best
    first).
    """
    affinities: list[float] = []
    for line in pdbqt_text.splitlines():
        if line.startswith("REMARK VINA RESULT:"):
            parts = line.split(":", 1)[1].split()
            if parts:
                try:
                    affinities.append(float(parts[0]))
                except ValueError:
                    continue
    return affinities


def dock(
    receptor_pdbqt: Path,
    ligand_pdbqt: Path,
    settings: VinaSettings,
    out_pdbqt: Path,
    timeout: float = 1800.0,
) -> list[float]:
    """Run Vina for one ligand and return its per-pose affinities (kcal/mol).

    Writes the docked poses to ``out_pdbqt``. Raises :class:`VinaError` if Vina
    fails or produces no parseable results.
    """
    cx, cy, cz = settings.center
    sx, sy, sz = settings.size
    cmd = [
        vina_binary(),
        "--receptor", str(receptor_pdbqt),
        "--ligand", str(ligand_pdbqt),
        "--center_x", str(cx),
        "--center_y", str(cy),
        "--center_z", str(cz),
        "--size_x", str(sx),
        "--size_y", str(sy),
        "--size_z", str(sz),
        "--exhaustiveness", str(settings.exhaustiveness),
        "--num_modes", str(settings.num_modes),
        "--energy_range", str(settings.energy_range),
        "--seed", str(settings.seed),
        "--out", str(out_pdbqt),
    ]
    if settings.cpu:
        cmd += ["--cpu", str(settings.cpu)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise VinaError(f"Vina timed out after {timeout:.0f}s") from exc

    if proc.returncode != 0:
        raise VinaError(f"Vina exited {proc.returncode}: {proc.stderr.strip()[:300]}")
    if not out_pdbqt.exists():
        raise VinaError("Vina produced no output file")

    affinities = parse_affinities(out_pdbqt.read_text())
    if not affinities:
        raise VinaError("Vina output had no VINA RESULT records")
    return affinities


def pdbqt_to_sdf(pdbqt_path: Path, sdf_path: Path) -> Path | None:
    """Convert a docked-pose PDBQT to SDF via OpenBabel (for pose artifacts).

    Returns the SDF path, or None if OpenBabel is unavailable or the conversion
    fails — pose export is a convenience and never fails the docking run.
    """
    obabel = shutil.which("obabel")
    if obabel is None:
        return None
    proc = subprocess.run(
        [obabel, str(pdbqt_path), "-O", str(sdf_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not Path(sdf_path).exists():
        return None
    return Path(sdf_path)
