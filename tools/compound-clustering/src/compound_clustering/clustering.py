"""
Compound Clustering

Groups a list of compounds — e.g. the keep-list that survived ``structure-alerts``
triage — into distinct chemical families.

Three clustering methods are selectable at runtime:

- ``butina`` (default): Morgan/ECFP fingerprints + Tanimoto distance, clustered with
  the Taylor-Butina algorithm (RDKit ``rdkit.ML.Cluster.Butina``). Threshold-based, so
  the number of families is discovered from the data rather than fixed up front; each
  cluster's first member is its centroid (the representative).
- ``scaffold``: Bemis-Murcko scaffold grouping (``rdkit.Chem.Scaffolds.MurckoScaffold``).
  Compounds that reduce to the same canonical ring-system scaffold form one family —
  the most interpretable view, with each cluster carrying its ``scaffold_smiles``.
- ``kmeans``: fingerprint bit-vectors clustered with scikit-learn ``KMeans`` at a
  user-specified ``n_clusters``; the representative is the member nearest the centroid.

Everything is delegated to RDKit (already the platform's chemistry dependency) and
scikit-learn — we do not re-implement fingerprints or clustering by hand.

Usage (CLI):
    echo '[{"smiles": "CCO", "id": "c1"}, {"smiles": "CCN", "id": "c2"}]' > input.json
    python -m compound_clustering.clustering --input input.json --output output.json

Usage (library):
    from compound_clustering.clustering import run
    result = run(
        [{"smiles": "CCO", "id": "c1"}, {"smiles": "CCN", "id": "c2"}],
        {"method": "butina", "cutoff": 0.35},
    )
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache

from rdkit import Chem, DataStructs
from rdkit.Chem import MACCSkeys, rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.ML.Cluster import Butina

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_METHOD = "butina"
DEFAULT_FINGERPRINT = "morgan"
DEFAULT_RADIUS = 2
DEFAULT_N_BITS = 2048
DEFAULT_CUTOFF = 0.35  # Butina *distance* threshold (≈ Tanimoto similarity 0.65)
DEFAULT_N_CLUSTERS = 5

VALID_METHODS = ("butina", "scaffold", "kmeans")
VALID_FINGERPRINTS = ("morgan", "ecfp4", "ecfp6", "maccs")

# Filenames for the optional visualization artifacts (written to the output folder).
GRID_IMAGE_FILE = "clusters.png"
CHEMICAL_SPACE_IMAGE_FILE = "chemical_space.png"


# ── Helpers ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1024)
def smiles_to_mol(smiles: str) -> Chem.Mol | None:
    """Convert SMILES to a sanitized RDKit Mol (cached). None if invalid."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is not None:
        Chem.SanitizeMol(mol)
    return mol


def _validate_compounds(raw_list: list) -> tuple[list[tuple[str, str]] | None, str | None]:
    """Validate the input compounds list.

    Each item must be an object with a non-empty ``smiles`` and a non-empty ``id``,
    and all ids must be unique. These are schema-level constraints, so any violation
    rejects the whole batch with an explanatory message (distinct from a
    present-but-unparseable SMILES, which is reported per-compound in ``errors``).

    Returns ``(compounds, error)`` where ``compounds`` is a list of ``(smiles, id)``
    tuples (or None on failure) and ``error`` is a human-readable message (or None).
    """
    compounds: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
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
        if cid in seen_ids:
            return None, f"duplicate id {cid!r} — every compound 'id' must be unique"
        seen_ids.add(cid)
        compounds.append((smiles, cid))
    return compounds, None


def _error_result(message: str, params: dict) -> dict:
    """Build a uniform empty result carrying a top-level error message."""
    return {
        "error": message,
        "results": [],
        "clusters": [],
        "errors": [],
        "summary": {
            "total": 0,
            "num_clusters": 0,
            "num_singletons": 0,
            "largest_cluster_size": 0,
            "invalid": 0,
            "method": str(params.get("method", DEFAULT_METHOD)).lower(),
        },
        "count": 0,
        "params_used": params,
    }


def _build_fingerprints(mols: list, fingerprint: str, radius: int, n_bits: int) -> list:
    """Compute a fingerprint per molecule.

    ``morgan`` honours ``radius``/``n_bits``; ``ecfp4``/``ecfp6`` are Morgan at the
    conventional radius 2/3; ``maccs`` is the fixed 167-bit MACCS key set.
    """
    fingerprint = fingerprint.lower()
    if fingerprint == "maccs":
        return [MACCSkeys.GenMACCSKeys(m) for m in mols]
    if fingerprint == "ecfp4":
        radius = 2
    elif fingerprint == "ecfp6":
        radius = 3
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    return [gen.GetFingerprint(m) for m in mols]


def _cluster_butina(fps: list, cutoff: float) -> list[tuple[int, ...]]:
    """Taylor-Butina clustering on a Tanimoto distance matrix.

    Builds the flattened lower-triangle distance list expected by
    ``Butina.ClusterData`` and returns clusters (each a tuple of molecule indices,
    centroid first), already ordered largest-first.
    """
    n = len(fps)
    dists: list[float] = []
    for i in range(1, n):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        dists.extend(1.0 - s for s in sims)
    return list(Butina.ClusterData(dists, n, cutoff, isDistData=True))


def _cluster_scaffold(
    mols: list, generic: bool
) -> tuple[list[tuple[int, ...]], list[str], list[str]]:
    """Group molecules by their Bemis-Murcko scaffold.

    Returns ``(clusters, cluster_scaffolds, scaffold_per_mol)`` where ``clusters`` are
    index tuples (largest-first), ``cluster_scaffolds`` is the canonical scaffold
    SMILES per cluster, and ``scaffold_per_mol`` is the scaffold SMILES per input
    molecule. Acyclic molecules reduce to an empty scaffold and share one family.
    """
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    scaffold_per_mol: list[str] = []
    for idx, mol in enumerate(mols):
        try:
            scaf = MurckoScaffold.GetScaffoldForMol(mol)
            if generic:
                scaf = MurckoScaffold.MakeScaffoldGeneric(scaf)
            scaf_smi = Chem.MolToSmiles(scaf)
        except Exception:
            scaf_smi = ""
        scaffold_per_mol.append(scaf_smi)
        if scaf_smi not in groups:
            groups[scaf_smi] = []
            order.append(scaf_smi)
        groups[scaf_smi].append(idx)

    paired = sorted(
        ((tuple(groups[s]), s) for s in order), key=lambda p: len(p[0]), reverse=True
    )
    clusters = [members for members, _ in paired]
    cluster_scaffolds = [scaf for _, scaf in paired]
    return clusters, cluster_scaffolds, scaffold_per_mol


def _cluster_kmeans(fps: list, n_clusters: int) -> list[tuple[int, ...]]:
    """K-means clustering on dense fingerprint bit-vectors (scikit-learn).

    ``n_clusters`` is capped at the number of molecules. Within each cluster the
    member nearest the centroid is placed first as the representative; clusters are
    returned largest-first.
    """
    import numpy as np
    from sklearn.cluster import KMeans

    n_bits = fps[0].GetNumBits()
    arr = np.zeros((len(fps), n_bits), dtype=np.float64)
    for i, fp in enumerate(fps):
        DataStructs.ConvertToNumpyArray(fp, arr[i])

    n_clusters = max(1, min(n_clusters, len(fps)))
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(arr)

    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(idx)

    clusters: list[tuple[int, ...]] = []
    for lab, idxs in groups.items():
        centroid = km.cluster_centers_[lab]
        rep = min(idxs, key=lambda i: float(np.linalg.norm(arr[i] - centroid)))
        ordered = [rep] + [i for i in idxs if i != rep]
        clusters.append(tuple(ordered))
    clusters.sort(key=len, reverse=True)
    return clusters


# ── Visualization (optional) ─────────────────────────────────────────────────


def _artifact_target(filename: str, params: dict) -> str:
    """Resolve where an output artifact should be written.

    Resolution order:
    1. ``params["output_dir"]`` — explicit override (set by the CLI to the dir of
       ``--output``, and by tests to a tmp dir).
    2. ``techneos_tool_runtime`` — the platform path; writes under ``{work_dir}/output/``
       where the worker collects artifacts. Only available inside the worker image.
    3. The current working directory — last-resort fallback.
    """
    out_dir = params.get("output_dir")
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        return os.path.join(out_dir, filename)
    try:
        from techneos_tool_runtime import artifact_path

        return str(artifact_path(filename))
    except Exception:
        return filename


def _render_grid(results: list[dict], path: str) -> None:
    """Draw a 2D structure grid grouped by cluster (representative starred)."""
    from rdkit.Chem import Draw

    ordered = sorted(results, key=lambda r: (r["cluster"], not r["is_representative"]))
    mols: list = []
    legends: list[str] = []
    for r in ordered:
        mol = Chem.MolFromSmiles(r.get("canonical_smiles") or r["smiles"])
        if mol is None:
            continue
        star = " ★" if r["is_representative"] else ""
        legends.append(f"{r['id']} [fam {r['cluster']}]{star}")
        mols.append(mol)

    per_row = min(5, max(1, len(mols)))
    img = Draw.MolsToGridImage(mols, legends=legends, molsPerRow=per_row, subImgSize=(260, 210))
    img.save(path)


def _render_chemical_space(
    mols: list, labels: list[int], names: list[str], path: str, radius: int, n_bits: int
) -> None:
    """Scatter a 2D PCA of Morgan fingerprints, colored by cluster."""
    import matplotlib

    matplotlib.use("Agg")  # headless — no display needed
    import matplotlib.pyplot as plt
    import numpy as np
    from sklearn.decomposition import PCA

    gen = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=n_bits)
    X = np.zeros((len(mols), n_bits))
    for i, mol in enumerate(mols):
        DataStructs.ConvertToNumpyArray(gen.GetFingerprint(mol), X[i])

    xy = PCA(n_components=2).fit_transform(X)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(xy[:, 0], xy[:, 1], c=labels, cmap="tab20", s=70, edgecolor="k", linewidth=0.3)
    for i, name in enumerate(names):
        ax.annotate(str(name), (xy[i, 0], xy[i, 1]), fontsize=7, alpha=0.8)
    ax.set_title("Chemical space (PCA of Morgan fingerprints), colored by cluster")
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def run(input_data: dict | list, params: dict | None = None) -> dict:
    """Cluster a list of compounds into chemical families.

    Each compound must be an object ``{"smiles": "...", "id": "..."}`` — both fields
    required — and every ``id`` must be unique across the list. Results are keyed by
    ``id``.

    Args:
        input_data: Either the compounds list directly (a ``list`` of
            ``{"smiles", "id"}`` objects, as the platform delivers it after parsing an
            uploaded file), or a dict carrying that list under a key (default
            ``"compounds"``; the platform auto-injects the actual key via the
            ``smiles_list_key`` param).
        params: Optional dict of options:
            - method (str): ``butina`` (default), ``scaffold`` or ``kmeans``.
            - fingerprint (str): ``morgan`` (default), ``ecfp4``, ``ecfp6`` or
              ``maccs`` (used by butina/kmeans).
            - radius (int): Morgan radius (default 2).
            - n_bits (int): Morgan fingerprint size (default 2048).
            - cutoff (float): Butina Tanimoto *distance* threshold (default 0.35).
            - n_clusters (int): number of clusters for kmeans (default 5).
            - generic_scaffold (bool): for scaffold method, reduce to the generic
              ring skeleton (default False).
            - render_grid (bool): also write a 2D structure grid grouped by cluster to
              ``clusters.png`` in the output folder (default False).
            - render_chemical_space (bool): also write a PCA scatter of Morgan
              fingerprints colored by cluster to ``chemical_space.png`` in the output
              folder (default False; needs ≥ 3 valid molecules).
            - output_dir (str): directory the image artifacts are written to. The CLI
              sets this to the dir of ``--output``; on the platform it is left unset
              and the techneos-tool-runtime output folder is used.
            - smiles_list_key (str): key under which the compounds list is found in
              ``input_data`` (default ``"compounds"``; auto-injected by the platform).

    Returns:
        Dict with:
            - results: Per-molecule records ``{id, smiles, canonical_smiles, cluster,
              is_representative[, scaffold_smiles]}``.
            - clusters: Per-cluster summaries ``{cluster_id, size, representative_id,
              member_ids[, scaffold_smiles]}``, ordered largest-first.
            - errors: ``{id, smiles}`` for compounds whose SMILES could not be parsed.
            - summary: ``{total, num_clusters, num_singletons, largest_cluster_size,
              invalid, method}``.
            - count: Number of valid molecules clustered.
            - params_used: The parameters that were applied.
            - images: Present only when a render was requested — maps ``grid`` /
              ``chemical_space`` to the written filename, or ``*_error`` to the reason
              a render was skipped.
        On a schema-level problem (bad/missing fields, duplicate id, unknown method,
        empty input) returns the same shape with a top-level ``error``.
    """
    params = params or {}
    # The platform auto-injects `smiles_list_key` = the input_schema array property
    # ("compounds") and delivers the parsed list under input_data[that key]. Honour
    # it; default to "compounds" for direct/CLI calls.
    list_key = params.get("smiles_list_key", "compounds")
    if isinstance(input_data, list):
        raw_list = input_data
    elif isinstance(input_data, dict):
        raw_list = input_data.get(list_key)
        if not isinstance(raw_list, list):
            # Paste mode delivers the list under params[list_key]; in upload mode
            # params[list_key] is a file descriptor (dict) — never treat that as the
            # compound list.
            paste = params.get(list_key)
            raw_list = paste if isinstance(paste, list) else []
    else:
        raw_list = []

    method = str(params.get("method", DEFAULT_METHOD)).lower()
    if method not in VALID_METHODS:
        return _error_result(
            f"Unknown method {method!r}. Allowed: {list(VALID_METHODS)}", params
        )

    fingerprint = str(params.get("fingerprint", DEFAULT_FINGERPRINT)).lower()
    if fingerprint not in VALID_FINGERPRINTS:
        return _error_result(
            f"Unknown fingerprint {fingerprint!r}. Allowed: {list(VALID_FINGERPRINTS)}",
            params,
        )

    if not raw_list:
        return _error_result("No compounds provided", params)

    compounds, validation_error = _validate_compounds(raw_list)
    if validation_error is not None:
        return _error_result(validation_error, params)

    radius = int(params.get("radius", DEFAULT_RADIUS))
    n_bits = int(params.get("n_bits", DEFAULT_N_BITS))
    cutoff = float(params.get("cutoff", DEFAULT_CUTOFF))
    n_clusters = int(params.get("n_clusters", DEFAULT_N_CLUSTERS))
    generic = bool(params.get("generic_scaffold", False))
    render_grid = bool(params.get("render_grid", False))
    render_space = bool(params.get("render_chemical_space", False))

    # Parse molecules; unparseable SMILES go to errors and are excluded from clustering.
    mols: list = []
    valid: list[tuple[str, str, str]] = []  # (smiles, id, canonical_smiles)
    errors: list[dict] = []
    for smi, cid in compounds:
        mol = smiles_to_mol(smi)
        if mol is None:
            errors.append({"id": cid, "smiles": smi})
        else:
            mols.append(mol)
            valid.append((smi, cid, Chem.MolToSmiles(mol)))

    if not mols:
        result = _error_result("No valid molecules to cluster", params)
        result["errors"] = errors
        result["summary"]["total"] = len(raw_list)
        result["summary"]["invalid"] = len(errors)
        return result

    cluster_scaffolds: list[str] | None = None
    scaffold_per_mol: list[str] | None = None
    if method == "scaffold":
        clusters, cluster_scaffolds, scaffold_per_mol = _cluster_scaffold(mols, generic)
    else:
        fps = _build_fingerprints(mols, fingerprint, radius, n_bits)
        if method == "butina":
            clusters = _cluster_butina(fps, cutoff)
        else:  # kmeans
            clusters = _cluster_kmeans(fps, n_clusters)

    # Assign 1-based cluster ids and find each cluster's representative (first member).
    cluster_of: dict[int, int] = {}
    rep_of: dict[int, int] = {}
    for cluster_id, members in enumerate(clusters, start=1):
        rep_of[cluster_id] = members[0]
        for m in members:
            cluster_of[m] = cluster_id

    results: list[dict] = []
    for i, (smi, cid, canon) in enumerate(valid):
        cluster_id = cluster_of[i]
        record = {
            "id": cid,
            "smiles": smi,
            "canonical_smiles": canon,
            "cluster": cluster_id,
            "is_representative": rep_of[cluster_id] == i,
        }
        if scaffold_per_mol is not None:
            record["scaffold_smiles"] = scaffold_per_mol[i]
        results.append(record)

    clusters_out: list[dict] = []
    num_singletons = 0
    largest = 0
    for cluster_id, members in enumerate(clusters, start=1):
        entry = {
            "cluster_id": cluster_id,
            "size": len(members),
            "representative_id": valid[members[0]][1],
            "member_ids": [valid[m][1] for m in members],
        }
        if cluster_scaffolds is not None:
            entry["scaffold_smiles"] = cluster_scaffolds[cluster_id - 1]
        clusters_out.append(entry)
        if len(members) == 1:
            num_singletons += 1
        largest = max(largest, len(members))

    summary = {
        "total": len(raw_list),
        "num_clusters": len(clusters),
        "num_singletons": num_singletons,
        "largest_cluster_size": largest,
        "invalid": len(errors),
        "method": method,
    }

    result = {
        "results": results,
        "clusters": clusters_out,
        "errors": errors,
        "summary": summary,
        "count": len(valid),
        "params_used": params,
    }

    # Optional visualization artifacts, written to the output folder. Each render is
    # isolated so a plotting failure (e.g. missing matplotlib) never fails clustering;
    # the reason is reported under images[*_error] instead.
    if render_grid or render_space:
        images: dict[str, str] = {}
        if render_grid:
            try:
                _render_grid(results, _artifact_target(GRID_IMAGE_FILE, params))
                images["grid"] = GRID_IMAGE_FILE
            except Exception as exc:  # noqa: BLE001 — surface, don't crash
                images["grid_error"] = str(exc)
        if render_space:
            if len(mols) < 3:
                images["chemical_space_error"] = (
                    "need at least 3 valid molecules for a PCA chemical-space plot"
                )
            else:
                try:
                    labels = [cluster_of[i] for i in range(len(mols))]
                    names = [valid[i][1] for i in range(len(mols))]
                    _render_chemical_space(
                        mols, labels, names,
                        _artifact_target(CHEMICAL_SPACE_IMAGE_FILE, params), radius, n_bits,
                    )
                    images["chemical_space"] = CHEMICAL_SPACE_IMAGE_FILE
                except Exception as exc:  # noqa: BLE001 — surface, don't crash
                    images["chemical_space_error"] = str(exc)
        result["images"] = images

    return result


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Compound Clustering — group compounds into chemical families (RDKit)"
    )
    parser.add_argument(
        "--input",
        default=os.environ.get("INPUT_FILE", "input.json"),
        help="Input JSON file with compounds (default: input.json)",
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

    # Default image artifacts next to the output JSON unless the caller pinned a dir.
    params.setdefault("output_dir", os.path.dirname(os.path.abspath(args.output)))

    result = run(input_data, params)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    summary = result.get("summary", {})
    print(
        f"Clustered {result['count']} molecules -> {args.output} "
        f"(method={summary.get('method')}, clusters={summary.get('num_clusters', 0)}, "
        f"singletons={summary.get('num_singletons', 0)}, invalid={summary.get('invalid', 0)})"
    )
    for key, value in result.get("images", {}).items():
        if key.endswith("_error"):
            print(f"  Image {key}: {value}")
        else:
            print(f"  Wrote image: {os.path.join(params['output_dir'], value)}")
    if result.get("error"):
        print(f"  Error: {result['error']}")


if __name__ == "__main__":
    main()
