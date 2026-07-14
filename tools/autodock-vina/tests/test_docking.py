"""Tests for autodock-vina.

Runs standalone (no pytest required):
    python test_docking.py
    python test_docking.py -v
Also works with pytest:
    uv run pytest tests

These cover the pure logic — input parsing, box resolution, affinity parsing,
ranking, and the error-result shape — none of which need the Vina binary or
RDKit/Meeko. A handful of prep tests run only when RDKit is importable. The full
container path (real docking) is exercised in test_container_smoke.py.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_pkg_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from autodock_vina import docking
from autodock_vina.vina import VinaSettings, parse_affinities

EXAMPLES = os.path.join(_pkg_dir, "examples")

SAMPLE_PDBQT = """\
MODEL 1
REMARK VINA RESULT:     -7.2      0.000      0.000
ATOM      1  C   LIG A   1       0.000   0.000   0.000  0.00  0.00     0.000 C
ENDMDL
MODEL 2
REMARK VINA RESULT:     -6.8      1.234      2.345
ATOM      1  C   LIG A   1       0.000   0.000   0.000  0.00  0.00     0.000 C
ENDMDL
"""


# ── Affinity parsing ──────────────────────────────────────────────────────


def test_parse_affinities_orders_as_written():
    affinities = parse_affinities(SAMPLE_PDBQT)
    assert affinities == [-7.2, -6.8]
    assert min(affinities) == -7.2


def test_parse_affinities_empty_when_no_records():
    assert parse_affinities("ATOM 1 C\nENDMDL\n") == []


# ── Compound loading / validation ─────────────────────────────────────────


def test_load_compounds_from_list():
    rows = [{"smiles": "CCO", "id": "a"}]
    assert docking._load_compounds(rows, {}) == rows


def test_load_compounds_from_json_path():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ligs.json")
        with open(path, "w") as f:
            json.dump([{"smiles": "CCO", "id": "a"}, {"smiles": "CCN", "id": "b"}], f)
        rows = docking._load_compounds({"compounds": path}, {})
        assert [r["id"] for r in rows] == ["a", "b"]


def test_load_compounds_from_smi_text():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ligs.smi")
        with open(path, "w") as f:
            f.write("CCO ethanol\nCCN\n")
        rows = docking._load_compounds({"compounds_file": path}, {})
        assert rows[0] == {"smiles": "CCO", "id": "ethanol"}
        assert rows[1]["smiles"] == "CCN"  # auto id for the unlabelled row


def test_validate_rejects_duplicate_ids():
    _, err = docking._validate_compounds([{"smiles": "CCO", "id": "x"}, {"smiles": "CCN", "id": "x"}])
    assert err is not None and "unique" in err


def test_validate_rejects_missing_smiles():
    _, err = docking._validate_compounds([{"id": "x"}])
    assert err is not None and "smiles" in err


# ── Receptor + box resolution ─────────────────────────────────────────────


def test_resolve_receptor_prefers_receptor_file():
    assert docking._resolve_receptor({"receptor_file": "/a.pdb", "receptor": "/b.pdb"}, {}) == "/a.pdb"
    assert docking._resolve_receptor({}, {"receptor": "/c.pdb"}) == "/c.pdb"


RECEPTOR = os.path.join(EXAMPLES, "receptor.pdb")


def test_resolve_box_explicit():
    import pathlib

    center, size = docking._resolve_box(
        {"center_x": 1, "center_y": 2, "center_z": 3, "size_x": 10},
        pathlib.Path(RECEPTOR), pathlib.Path(EXAMPLES),
    )
    assert center == [1.0, 2.0, 3.0]
    assert size == [10.0, 20.0, 20.0]  # defaults for y/z


def test_resolve_box_defaults_to_receptor_centroid():
    import pathlib

    from autodock_vina.prep import receptor_center

    center, size = docking._resolve_box({}, pathlib.Path(RECEPTOR), pathlib.Path(EXAMPLES))
    assert center == receptor_center(pathlib.Path(RECEPTOR))  # no center given -> centroid
    assert size == [20.0, 20.0, 20.0]


def test_resolve_box_from_reference():
    import pathlib

    with tempfile.TemporaryDirectory() as tmp:
        ref = pathlib.Path(tmp) / "ref.pdb"
        ref.write_text(
            "ATOM      1  C   LIG A   1       0.000   0.000   0.000  1.00  0.00           C\n"
            "ATOM      2  C   LIG A   1       4.000   2.000   6.000  1.00  0.00           C\n"
        )
        center, size = docking._resolve_box(
            {"box_from_ref": True, "reference_ligand": str(ref), "ref_padding": 1.0},
            pathlib.Path(RECEPTOR), pathlib.Path(tmp),
        )
        assert center == [2.0, 1.0, 3.0]
        assert size == [6.0, 4.0, 8.0]  # extent + 2*padding


# ── run() error paths (no binary needed) ──────────────────────────────────


def test_run_no_compounds_returns_error():
    result = docking.run({"compounds": []}, {})
    assert result["error"] == "No compounds provided"
    assert result["results"] == [] and result["count"] == 0


def test_run_missing_receptor_returns_error():
    result = docking.run(
        {"compounds": [{"smiles": "CCO", "id": "a"}]},
        {"search_box": {"center_x": 0, "center_y": 0, "center_z": 0}},
    )
    assert "Receptor file not found" in result["error"]


def test_run_box_from_ref_without_reference_errors():
    result = docking.run(
        {"compounds": [{"smiles": "CCO", "id": "a"}], "receptor_file": RECEPTOR},
        {"search_box": {"box_from_ref": True}},  # no reference_ligand
    )
    assert "reference" in result["error"]


# ── Ligand prep (only when RDKit is importable) ───────────────────────────


def test_ligand_pdbqt_when_tooling_present():
    try:
        import rdkit  # noqa: F401
        import meeko  # noqa: F401
    except ImportError:
        return  # tooling absent locally — covered in the container smoke test
    import pathlib

    from autodock_vina.prep import prepare_ligand

    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "lig.pdbqt"
        prepare_ligand("CCO", out, seed=1)
        text = out.read_text()
        assert "ATOM" in text or "HETATM" in text


# ── Example assets sanity ─────────────────────────────────────────────────


def test_examples_present_and_valid():
    with open(os.path.join(EXAMPLES, "input.json")) as f:
        compounds = json.load(f)
    assert len(compounds) >= 2 and all("smiles" in c and "id" in c for c in compounds)
    with open(os.path.join(EXAMPLES, "params.json")) as f:
        params = json.load(f)
    assert {"center_x", "center_y", "center_z"} <= set(params["search_box"])
    assert os.path.exists(os.path.join(EXAMPLES, "receptor.pdb"))


def test_vina_settings_dataclass():
    s = VinaSettings(center=(1, 2, 3), size=(20, 20, 20), exhaustiveness=16)
    assert s.center == (1, 2, 3) and s.exhaustiveness == 16


# ── Standalone runner ─────────────────────────────────────────────────────


def _run_all(verbose: bool) -> int:
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in funcs:
        try:
            fn()
            if verbose:
                print(f"  PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(funcs) - failures}/{len(funcs)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all(verbose="-v" in sys.argv))
