"""AutoDock Vina docking — ``run(inputs, params) -> dict`` contract.

Docks a set of **representative molecules** (the keep-list that survived
``structure-alerts`` / ``compound-clustering`` triage) into a protein receptor
and ranks them by predicted binding affinity, so you can see *which* chemotypes
actually engage the target and *how strongly*.

Pipeline per run:

1. **Receptor** (raw PDB at ``inputs["receptor_file"]``) is prepped once —
   waters/heteroatoms stripped, hydrogens + Gasteiger charges added, written as
   a rigid receptor PDBQT (see :mod:`autodock_vina.prep`).
2. **Search box** is resolved from the ``search_box`` param object — explicit
   ``center_*`` / ``size_*``, or derived from a reference ligand when
   ``box_from_ref`` is set; with no center given it defaults to the receptor
   centroid (a default-size box over the structure).
3. **Each ligand** SMILES is embedded to 3D (RDKit) and written to a ligand
   PDBQT (Meeko), then docked with the ``vina`` binary
   (:mod:`autodock_vina.vina`). Unparseable / un-embeddable SMILES are recorded
   per-compound in ``errors`` and never fail the batch.
4. Results are **ranked** by best (most negative) affinity.

Optional artifacts (written to the output folder): per-ligand docked-pose SDFs
(``write_poses``) and a horizontal bar chart of best affinities
(``render_scores`` → ``scores.png``).

Input shapes (robust to how the platform / CLI / tests deliver them):
    inputs:
        compounds        list[{smiles,id}] OR a path to a SMILES file
        compounds_file   path to a SMILES file (worker upload form)
        receptor_file    path to the receptor PDB (worker upload form)
        receptor         path to the receptor PDB (pass-through form)
    params: see ``parameters_schema`` in tool_def.json.

A pass-through ``parse()`` is exported so the generic runner hands ``run`` raw
file *paths* (the receptor must not be run through the SMILES parser); ``run``
parses the SMILES file itself.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from autodock_vina.prep import (
    PrepError,
    box_from_reference,
    prepare_ligand,
    prepare_receptor,
    receptor_center,
)
from autodock_vina.vina import VinaSettings, dock, pdbqt_to_sdf, vina_version

DEFAULT_SIZE = 20.0
DEFAULT_EXHAUSTIVENESS = 8
DEFAULT_NUM_MODES = 9
DEFAULT_ENERGY_RANGE = 3.0
DEFAULT_SEED = 0
DEFAULT_PH = 7.4
DEFAULT_REF_PADDING = 4.0

SCORES_IMAGE_FILE = "scores.png"


# ── Runner integration ───────────────────────────────────────────────────────


def parse(file_path: str, params: dict | None = None) -> str:  # noqa: ARG001
    """Pass-through parser for the generic runner.

    The runner applies one parser to every uploaded file. Returning the raw path
    keeps the receptor PDB from being run through the SMILES parser; ``run``
    loads and parses the SMILES file itself.
    """
    return file_path


# ── Input handling ───────────────────────────────────────────────────────────


def _read_compounds_file(path: str) -> list[dict]:
    """Read a SMILES file into ``[{smiles, id}, ...]``.

    Prefers the platform's shared SMILES parser (handles JSON / CSV / TSV / SMI
    / SDF); falls back to a small JSON / whitespace reader when the runtime
    isn't importable (e.g. local CLI without techneos-tool-runtime installed).
    """
    try:
        from techneos_tool_runtime import parsers

        rows = parsers.parse(path, input_kind="smiles_list")
        if rows:
            return rows
    except Exception:  # noqa: BLE001 - fall back to local readers
        pass

    text = Path(path).read_text()
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("compounds") or data.get("smiles") or []
        return list(data) if isinstance(data, list) else []

    # Plain SMILES text: "<smiles> [id]" per line.
    out: list[dict] = []
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        out.append({"smiles": parts[0], "id": parts[1] if len(parts) > 1 else f"lig-{i + 1}"})
    return out


def _load_compounds(inputs, params: dict) -> list:
    """Resolve the ligand list from whichever shape the caller provided."""
    if isinstance(inputs, list):
        return inputs
    candidates = [
        inputs.get("compounds") if isinstance(inputs, dict) else None,
        inputs.get("compounds_file") if isinstance(inputs, dict) else None,
        params.get("compounds"),
    ]
    for cand in candidates:
        if isinstance(cand, list):
            return cand
        if isinstance(cand, str) and cand:
            return _read_compounds_file(cand)
    return []


def _resolve_receptor(inputs, params: dict) -> str | None:
    """Find the receptor PDB path across the upload / pass-through / param forms."""
    if isinstance(inputs, dict):
        for key in ("receptor_file", "receptor"):
            val = inputs.get(key)
            if isinstance(val, str) and val:
                return val
    for key in ("receptor", "receptor_file"):
        val = params.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _validate_compounds(raw_list: list) -> tuple[list[tuple[str, str]] | None, str | None]:
    """Validate ``[{smiles,id}]`` — both fields required, ids unique."""
    compounds: list[tuple[str, str]] = []
    seen: set[str] = set()
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
        if cid in seen:
            return None, f"duplicate id {cid!r} — every compound 'id' must be unique"
        seen.add(cid)
        compounds.append((smiles, cid))
    return compounds, None


def _resolve_box(
    cfg: dict, receptor_path: Path, receptor_dir: Path
) -> tuple[list[float], list[float]]:
    """Resolve the docking box (center, size) in Ångström from ``search_box``.

    Three ways the box is determined, in priority order:
    1. ``box_from_ref`` — bounding box of a reference ligand (``reference_ligand``)
       plus ``ref_padding``.
    2. Explicit ``center_{x,y,z}`` (all three) with ``size_{x,y,z}`` (default 20).
    3. Default — center on the **receptor centroid** with the default-size box, so
       an unspecified box still docks over the structure.

    Raises ``ValueError`` only when ``box_from_ref`` is set without a reference.
    """
    if cfg.get("box_from_ref"):
        ref = cfg.get("reference_ligand")
        if not ref:
            raise ValueError("box_from_ref is set but no 'reference_ligand' was provided")
        ref_path = Path(ref)
        if not ref_path.is_absolute() and not ref_path.exists():
            ref_path = receptor_dir / ref
        return box_from_reference(
            ref_path, padding=float(cfg.get("ref_padding", DEFAULT_REF_PADDING))
        )

    have_center = all(cfg.get(a) is not None for a in ("center_x", "center_y", "center_z"))
    if have_center:
        center = [float(cfg["center_x"]), float(cfg["center_y"]), float(cfg["center_z"])]
    else:
        # No (complete) center given — default to the receptor centroid.
        center = receptor_center(receptor_path)

    size = [
        float(cfg.get("size_x", DEFAULT_SIZE)),
        float(cfg.get("size_y", DEFAULT_SIZE)),
        float(cfg.get("size_z", DEFAULT_SIZE)),
    ]
    return center, size


# ── Artifacts ────────────────────────────────────────────────────────────────


def _artifact_target(filename: str, params: dict) -> Path:
    """Resolve where an output artifact should be written.

    Order: explicit ``params["output_dir"]`` (CLI / tests) → techneos-tool-runtime
    output folder (on the platform) → current working directory.
    """
    out_dir = params.get("output_dir")
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        return Path(out_dir) / filename
    try:
        from techneos_tool_runtime import artifact_path

        return Path(artifact_path(filename))
    except Exception:  # noqa: BLE001
        return Path(filename)


def _render_scores(results: list[dict], path: Path) -> None:
    """Horizontal bar chart of best affinity per ligand (best at top)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ordered = sorted(results, key=lambda r: r["affinity"])
    labels = [r["id"] for r in ordered]
    values = [r["affinity"] for r in ordered]

    fig, ax = plt.subplots(figsize=(8, max(2.0, 0.4 * len(ordered) + 1)))
    ax.barh(range(len(ordered)), values, color="#3b7dd8", edgecolor="k", linewidth=0.3)
    ax.set_yticks(range(len(ordered)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()  # best (most negative) at the top
    ax.set_xlabel("Predicted binding affinity (kcal/mol)")
    ax.set_title("AutoDock Vina — best affinity per molecule")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def _error_result(message: str, params: dict) -> dict:
    """Uniform empty result carrying a top-level error message."""
    return {
        "error": message,
        "results": [],
        "ranking": [],
        "errors": [],
        "summary": {"total": 0, "docked": 0, "failed": 0, "best_id": None, "best_affinity": None},
        "count": 0,
        "params_used": params,
    }


# ── Entry point ──────────────────────────────────────────────────────────────


def run(inputs, params: dict | None = None) -> dict:
    """Dock representative molecules into a receptor and rank by affinity.

    Args:
        inputs: Ligands as ``[{smiles, id}]`` (or a path to a SMILES file under
            ``compounds`` / ``compounds_file``) plus the receptor PDB under
            ``receptor_file`` / ``receptor``.
        params: See ``parameters_schema`` (``search_box`` object with
            center/size/box_from_ref/reference_ligand, plus exhaustiveness,
            num_modes, energy_range, seed, ph, remove_waters, remove_hetero,
            write_poses, render_scores).

    Returns:
        ``{results, ranking, errors, summary, count, params_used[, images]}``.
        On a schema-level problem (no compounds, missing receptor, bad box)
        the same shape is returned with a top-level ``error``.
    """
    params = params or {}

    raw_list = _load_compounds(inputs, params)
    if not raw_list:
        return _error_result("No compounds provided", params)

    compounds, validation_error = _validate_compounds(raw_list)
    if validation_error is not None:
        return _error_result(validation_error, params)

    receptor_path = _resolve_receptor(inputs, params)
    if not receptor_path or not Path(receptor_path).exists():
        return _error_result(
            f"Receptor file not found (looked for receptor_file / receptor): {receptor_path!r}",
            params,
        )
    receptor_dir = Path(receptor_path).resolve().parent

    search_box = params.get("search_box") if isinstance(params.get("search_box"), dict) else {}
    try:
        center, size = _resolve_box(search_box, Path(receptor_path), receptor_dir)
    except (ValueError, PrepError) as exc:
        return _error_result(str(exc), params)

    settings = VinaSettings(
        center=(center[0], center[1], center[2]),
        size=(size[0], size[1], size[2]),
        exhaustiveness=int(params.get("exhaustiveness", DEFAULT_EXHAUSTIVENESS)),
        num_modes=int(params.get("num_modes", DEFAULT_NUM_MODES)),
        energy_range=float(params.get("energy_range", DEFAULT_ENERGY_RANGE)),
        seed=int(params.get("seed", DEFAULT_SEED)),
    )
    ph = float(params.get("ph", DEFAULT_PH))
    write_poses = bool(params.get("write_poses", False))
    render_scores = bool(params.get("render_scores", False))

    results: list[dict] = []
    errors: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        # Prep the receptor once for the whole batch.
        try:
            receptor_pdbqt = prepare_receptor(
                Path(receptor_path),
                tmp_dir / "receptor.pdbqt",
                remove_waters=bool(params.get("remove_waters", True)),
                remove_hetero=bool(params.get("remove_hetero", False)),
                ph=ph,
            )
        except PrepError as exc:
            return _error_result(f"Receptor prep failed: {exc}", params)

        for smiles, cid in compounds:
            lig_pdbqt = tmp_dir / f"{_safe(cid)}.pdbqt"
            out_pdbqt = tmp_dir / f"{_safe(cid)}_out.pdbqt"
            try:
                prepare_ligand(smiles, lig_pdbqt, seed=settings.seed, ph=ph)
                affinities = dock(receptor_pdbqt, lig_pdbqt, settings, out_pdbqt)
            except Exception as exc:  # noqa: BLE001 - per-compound failure, keep going
                errors.append({"id": cid, "smiles": smiles, "reason": str(exc)})
                continue

            record = {
                "id": cid,
                "smiles": smiles,
                "affinity": round(min(affinities), 3),
                "num_poses": len(affinities),
                "pose_affinities": [round(a, 3) for a in affinities],
            }
            if write_poses:
                sdf_name = f"{_safe(cid)}_poses.sdf"
                sdf = pdbqt_to_sdf(out_pdbqt, _artifact_target(sdf_name, params))
                if sdf is not None:
                    record["pose_file"] = sdf_name
            results.append(record)

    # Rank by best (most negative) affinity.
    results.sort(key=lambda r: r["affinity"])
    for rank, record in enumerate(results, start=1):
        record["rank"] = rank
    ranking = [r["id"] for r in results]

    summary = {
        "total": len(compounds),
        "docked": len(results),
        "failed": len(errors),
        "best_id": results[0]["id"] if results else None,
        "best_affinity": results[0]["affinity"] if results else None,
        "box": {"center": center, "size": size},
        "vina_version": vina_version(),
    }

    result = {
        "results": results,
        "ranking": ranking,
        "errors": errors,
        "summary": summary,
        "count": len(results),
        "params_used": params,
    }

    if render_scores and results:
        try:
            _render_scores(results, _artifact_target(SCORES_IMAGE_FILE, params))
            result["images"] = {"scores": SCORES_IMAGE_FILE}
        except Exception as exc:  # noqa: BLE001 - never fail docking on a plot
            result["images"] = {"scores_error": str(exc)}

    return result


def _safe(name: str) -> str:
    """Filesystem-safe slug for per-ligand intermediate / artifact filenames."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name)) or "lig"


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for local runs."""
    parser = argparse.ArgumentParser(
        description="AutoDock Vina docking — rank molecules by binding affinity to a receptor"
    )
    parser.add_argument("--input", default=os.environ.get("INPUT_FILE", "input.json"),
                        help="SMILES file of ligands ([{smiles,id}] JSON, CSV/TSV, or .smi)")
    parser.add_argument("--receptor", default=os.environ.get("RECEPTOR_FILE", "receptor.pdb"),
                        help="Receptor PDB file")
    parser.add_argument("--params", default=os.environ.get("PARAMS_FILE", "params.json"),
                        help="Parameters JSON file")
    parser.add_argument("--output", default=os.environ.get("OUTPUT_FILE", "output.json"),
                        help="Output JSON file")
    args = parser.parse_args()

    params = {}
    if os.path.exists(args.params):
        with open(args.params) as f:
            params = json.load(f)
    # Default artifacts next to the output JSON unless the caller pinned a dir.
    params.setdefault("output_dir", os.path.dirname(os.path.abspath(args.output)))

    inputs = {"compounds": args.input, "receptor_file": args.receptor}
    result = run(inputs, params)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    s = result.get("summary", {})
    if result.get("error"):
        print(f"Error: {result['error']}")
        return
    print(
        f"Docked {s.get('docked', 0)}/{s.get('total', 0)} molecules -> {args.output} "
        f"(best={s.get('best_id')} @ {s.get('best_affinity')} kcal/mol, "
        f"failed={s.get('failed', 0)})"
    )
    for key, value in result.get("images", {}).items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
