"""Tests for compound-clustering (RDKit Butina / Murcko scaffold + sklearn k-means).

Runs standalone (no pytest required):
    python test_clustering.py
    python test_clustering.py -v

Also works with pytest:
    uv run pytest tests
"""

import json
import os
import sys
import traceback

# Allow importing from the package when run standalone
_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_pkg_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from compound_clustering.clustering import (  # noqa: E402
    VALID_FINGERPRINTS,
    VALID_METHODS,
    _validate_compounds,
    run,
    smiles_to_mol,
)

# Two tight families plus a lone outlier.
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
ASPIRIN_ME = "CC(=O)Oc1ccccc1C(=O)OC"  # methyl ester analog of aspirin
ASPIRIN_PR = "OC(=O)c1ccccc1OC(=O)CC"  # propanoyl salicylate analog
SULFA1 = "Cc1ccc(cc1)S(=O)(=O)N"  # toluenesulfonamide
SULFA2 = "Nc1ccc(cc1)S(=O)(=O)N"  # sulfanilamide
GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"  # sugar — dissimilar to the aromatics

# Shared-scaffold pair (same benzanilide core, different ring substituent).
SCAF_A = "O=C(Nc1ccccc1)c1ccccc1"
SCAF_B = "O=C(Nc1ccc(C)cc1)c1ccccc1"


def _wrap(pairs):
    """Build a compounds input dict from (smiles, id) pairs."""
    return {"compounds": [{"smiles": s, "id": i} for s, i in pairs]}


# ---------------------------------------------------------------------------
# constants / validation
# ---------------------------------------------------------------------------


def test_method_and_fingerprint_constants():
    assert set(VALID_METHODS) == {"butina", "scaffold", "kmeans"}
    assert "morgan" in VALID_FINGERPRINTS and "maccs" in VALID_FINGERPRINTS


def test_validate_ok():
    compounds, err = _validate_compounds([{"smiles": "CCO", "id": "a"}, {"smiles": "CCN", "id": "b"}])
    assert err is None
    assert compounds == [("CCO", "a"), ("CCN", "b")]


def test_validate_requires_id():
    compounds, err = _validate_compounds([{"smiles": "CCO"}])
    assert compounds is None
    assert "id" in err


def test_validate_requires_unique_ids():
    compounds, err = _validate_compounds(
        [{"smiles": "CCO", "id": "dup"}, {"smiles": "CCN", "id": "dup"}]
    )
    assert compounds is None
    assert "unique" in err


def test_smiles_to_mol():
    assert smiles_to_mol("CCO") is not None
    assert smiles_to_mol("not_a_smiles") is None


# ---------------------------------------------------------------------------
# butina
# ---------------------------------------------------------------------------


def test_butina_groups_analogs_separates_outlier():
    result = run(
        _wrap(
            [
                (ASPIRIN, "asa"),
                (ASPIRIN_ME, "asa_me"),
                (ASPIRIN_PR, "asa_pr"),
                (SULFA1, "sulfa1"),
                (SULFA2, "sulfa2"),
                (GLUCOSE, "glucose"),
            ]
        ),
        {"method": "butina", "cutoff": 0.45},
    )
    assert "error" not in result
    assert result["count"] == 6
    assert result["summary"]["method"] == "butina"

    cluster_of = {r["id"]: r["cluster"] for r in result["results"]}
    # aspirin analogs share a family; sulfonamides share a family
    assert cluster_of["asa"] == cluster_of["asa_me"] == cluster_of["asa_pr"]
    assert cluster_of["sulfa1"] == cluster_of["sulfa2"]
    # distinct families
    assert cluster_of["asa"] != cluster_of["sulfa1"]
    assert cluster_of["glucose"] != cluster_of["asa"]
    assert cluster_of["glucose"] != cluster_of["sulfa1"]


def test_butina_clusters_summary_consistent():
    result = run(
        _wrap([(ASPIRIN, "a"), (ASPIRIN_ME, "b"), (GLUCOSE, "g")]),
        {"method": "butina", "cutoff": 0.4},
    )
    assert result["summary"]["num_clusters"] == len(result["clusters"])
    total_members = sum(c["size"] for c in result["clusters"])
    assert total_members == result["count"]
    # exactly one representative per cluster
    reps = [r["id"] for r in result["results"] if r["is_representative"]]
    assert len(reps) == result["summary"]["num_clusters"]
    # clusters ordered largest-first
    sizes = [c["size"] for c in result["clusters"]]
    assert sizes == sorted(sizes, reverse=True)


def test_butina_each_compound_assigned_once():
    result = run(_wrap([(ASPIRIN, "a"), (SULFA1, "b"), (GLUCOSE, "g")]), {"method": "butina"})
    assigned = [mid for c in result["clusters"] for mid in c["member_ids"]]
    assert sorted(assigned) == ["a", "b", "g"]


# ---------------------------------------------------------------------------
# scaffold
# ---------------------------------------------------------------------------


def test_scaffold_groups_shared_core():
    result = run(
        _wrap([(SCAF_A, "a"), (SCAF_B, "b"), (GLUCOSE, "g")]),
        {"method": "scaffold"},
    )
    assert "error" not in result
    cluster_of = {r["id"]: r["cluster"] for r in result["results"]}
    # same benzanilide core (one bears an extra ring methyl) → same family
    assert cluster_of["a"] == cluster_of["b"]
    assert cluster_of["g"] != cluster_of["a"]
    # scaffold smiles surfaced per-compound and per-cluster
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id["a"]["scaffold_smiles"] == by_id["b"]["scaffold_smiles"]
    assert all("scaffold_smiles" in c for c in result["clusters"])


# ---------------------------------------------------------------------------
# kmeans
# ---------------------------------------------------------------------------


def test_kmeans_respects_n_clusters():
    result = run(
        _wrap(
            [
                (ASPIRIN, "asa"),
                (ASPIRIN_ME, "asa_me"),
                (SULFA1, "sulfa1"),
                (SULFA2, "sulfa2"),
                (GLUCOSE, "glucose"),
            ]
        ),
        {"method": "kmeans", "n_clusters": 3},
    )
    assert "error" not in result
    assert result["summary"]["num_clusters"] == 3
    assert result["count"] == 5


def test_kmeans_caps_n_clusters_at_population():
    result = run(_wrap([(ASPIRIN, "a"), (GLUCOSE, "g")]), {"method": "kmeans", "n_clusters": 10})
    assert result["summary"]["num_clusters"] <= 2


# ---------------------------------------------------------------------------
# errors / edge cases
# ---------------------------------------------------------------------------


def test_invalid_smiles_in_errors():
    result = run(_wrap([(ASPIRIN, "good"), ("not_a_smiles", "bad")]), {"method": "butina"})
    assert result["errors"] == [{"id": "bad", "smiles": "not_a_smiles"}]
    assert result["count"] == 1
    assert result["summary"]["invalid"] == 1


def test_all_invalid_returns_error():
    result = run(_wrap([("not_a_smiles", "bad")]), {"method": "butina"})
    assert "error" in result
    assert result["count"] == 0
    assert result["summary"]["invalid"] == 1


def test_empty_input_errors():
    result = run({"compounds": []})
    assert "error" in result
    assert result["count"] == 0


def test_unknown_method_errors():
    result = run(_wrap([(ASPIRIN, "a")]), {"method": "dbscan"})
    assert "error" in result
    assert result["count"] == 0


def test_unknown_fingerprint_errors():
    result = run(_wrap([(ASPIRIN, "a")]), {"fingerprint": "bogus"})
    assert "error" in result


def test_duplicate_id_errors():
    result = run(_wrap([(ASPIRIN, "x"), (SULFA1, "x")]))
    assert "error" in result
    assert "unique" in result["error"]


def test_maccs_fingerprint_runs():
    result = run(
        _wrap([(ASPIRIN, "a"), (ASPIRIN_ME, "b"), (GLUCOSE, "g")]),
        {"method": "butina", "fingerprint": "maccs", "cutoff": 0.5},
    )
    assert "error" not in result
    assert result["count"] == 3


# ---------------------------------------------------------------------------
# input plumbing
# ---------------------------------------------------------------------------


def test_bare_list_input():
    result = run([{"smiles": ASPIRIN, "id": "a"}, {"smiles": SULFA1, "id": "b"}])
    assert result["count"] == 2
    assert "error" not in result


def test_smiles_list_key_injection():
    result = run({"molecules": [{"smiles": ASPIRIN, "id": "a"}]}, {"smiles_list_key": "molecules"})
    assert result["count"] == 1
    assert "error" not in result


def test_ignores_upload_descriptor_in_params():
    result = run(
        {"compounds": []},
        {"smiles_list_key": "compounds", "compounds": {"type": "upload", "storage_key": "x"}},
    )
    assert "error" in result
    assert result["count"] == 0


def test_params_used_passthrough():
    params = {"method": "butina", "cutoff": 0.3}
    result = run(_wrap([(ASPIRIN, "a")]), params)
    assert result["params_used"] == params


# ---------------------------------------------------------------------------
# visualization
# ---------------------------------------------------------------------------

_VIZ_INPUT = _wrap(
    [
        (ASPIRIN, "asa"),
        (ASPIRIN_ME, "asa_me"),
        (ASPIRIN_PR, "asa_pr"),
        (SULFA1, "sulfa1"),
        (SULFA2, "sulfa2"),
        (GLUCOSE, "glucose"),
    ]
)


def test_no_images_key_when_not_requested():
    result = run(_wrap([(ASPIRIN, "a"), (GLUCOSE, "g")]), {"method": "butina"})
    assert "images" not in result


def test_render_grid_writes_png(tmp_path):
    result = run(_VIZ_INPUT, {"method": "butina", "render_grid": True, "output_dir": str(tmp_path)})
    assert result["images"]["grid"] == "clusters.png"
    png = tmp_path / "clusters.png"
    assert png.exists() and png.stat().st_size > 0
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_chemical_space_writes_png(tmp_path):
    result = run(
        _VIZ_INPUT,
        {"method": "butina", "render_chemical_space": True, "output_dir": str(tmp_path)},
    )
    assert result["images"]["chemical_space"] == "chemical_space.png"
    png = tmp_path / "chemical_space.png"
    assert png.exists() and png.stat().st_size > 0


def test_render_both_images(tmp_path):
    result = run(
        _VIZ_INPUT,
        {
            "method": "scaffold",
            "render_grid": True,
            "render_chemical_space": True,
            "output_dir": str(tmp_path),
        },
    )
    assert (tmp_path / "clusters.png").exists()
    assert (tmp_path / "chemical_space.png").exists()
    assert set(result["images"]) == {"grid", "chemical_space"}


def test_chemical_space_needs_three_molecules(tmp_path):
    result = run(
        _wrap([(ASPIRIN, "a"), (GLUCOSE, "g")]),
        {"render_chemical_space": True, "output_dir": str(tmp_path)},
    )
    assert "chemical_space_error" in result["images"]
    assert not (tmp_path / "chemical_space.png").exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_with_files(tmp_path):
    from compound_clustering.clustering import main

    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps(
            [
                {"smiles": ASPIRIN, "id": "a"},
                {"smiles": ASPIRIN_ME, "id": "b"},
                {"smiles": GLUCOSE, "id": "g"},
            ]
        )
    )
    output_file = tmp_path / "output.json"
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps({"method": "butina", "cutoff": 0.4}))

    old_argv = sys.argv
    sys.argv = [
        "clustering.py",
        "--input",
        str(input_file),
        "--output",
        str(output_file),
        "--params",
        str(params_file),
    ]
    try:
        main()
    finally:
        sys.argv = old_argv

    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["count"] == 3
    assert data["summary"]["method"] == "butina"


# ---------------------------------------------------------------------------
# Standalone test runner (no pytest dependency)
# ---------------------------------------------------------------------------


def _collect_tests():
    return [obj for name, obj in globals().items() if name.startswith("test_") and callable(obj)]


def _run_tests(verbose: bool = False):
    tests = _collect_tests()
    passed = 0
    failed = 0
    errors = []

    for t in tests:
        try:
            if "tmp_path" in t.__code__.co_varnames:
                continue
            t()
            passed += 1
            if verbose:
                print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            errors.append((t.__name__, str(e)))
            if verbose:
                print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            errors.append((t.__name__, f"{type(e).__name__}: {e}"))
            if verbose:
                print(f"  ERROR {t.__name__}: {e}")
                traceback.print_exc()

    total = len(tests)
    print(f"\n{'=' * 40}")
    if failed:
        print(f"FAILED: {failed}/{total} ({passed}/{total} passed)")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
    else:
        skipped = sum(1 for t in tests if "tmp_path" in t.__code__.co_varnames)
        print(f"PASSED: {passed}/{total} ({skipped} skipped — pytest-only)")
    return failed


if __name__ == "__main__":
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    sys.exit(_run_tests(verbose=verbose))
