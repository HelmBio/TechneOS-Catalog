"""Tests for structure-alerts (RDKit FilterCatalog-based).

Runs standalone (no pytest required):
    python test_checker.py
    python test_checker.py -v

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

from structure_alerts.checker import (  # noqa: E402
    CATALOG_NAMES,
    DEFAULT_CATALOGS,
    _resolve_catalogs,
    _validate_compounds,
    run,
    screen_molecule,
    smiles_to_mol,
)

# Well-known probes
CAFFEINE = "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"  # clean under PAINS+BRENK
CATECHOL = "Oc1ccccc1O"  # PAINS + Brenk + NIH hit
ACETYL_CHLORIDE = "CC(=O)Cl"  # reactive acyl halide (Brenk + custom)
MICHAEL = "C=CC(=O)C"  # Michael acceptor (Brenk + custom)


def _c(smiles, cid):
    """Build a single-compound input dict."""
    return {"compounds": [{"smiles": smiles, "id": cid}]}


# ---------------------------------------------------------------------------
# _validate_compounds
# ---------------------------------------------------------------------------


def test_validate_ok():
    compounds, err = _validate_compounds([{"smiles": "CCO", "id": "a"}, {"smiles": "CCN", "id": "b"}])
    assert err is None
    assert compounds == [("CCO", "a"), ("CCN", "b")]


def test_validate_rejects_plain_string():
    compounds, err = _validate_compounds(["CCO"])
    assert compounds is None
    assert "object" in err


def test_validate_requires_smiles():
    compounds, err = _validate_compounds([{"id": "a"}])
    assert compounds is None
    assert "smiles" in err


def test_validate_requires_id():
    compounds, err = _validate_compounds([{"smiles": "CCO"}])
    assert compounds is None
    assert "id" in err


def test_validate_rejects_empty_id():
    compounds, err = _validate_compounds([{"smiles": "CCO", "id": ""}])
    assert compounds is None
    assert "id" in err


def test_validate_requires_unique_ids():
    compounds, err = _validate_compounds(
        [{"smiles": "CCO", "id": "dup"}, {"smiles": "CCN", "id": "dup"}]
    )
    assert compounds is None
    assert "unique" in err
    assert "dup" in err


def test_validate_id_coerced_to_str():
    compounds, err = _validate_compounds([{"smiles": "CCO", "id": 1}, {"smiles": "CCN", "id": 2}])
    assert err is None
    assert compounds == [("CCO", "1"), ("CCN", "2")]


# ---------------------------------------------------------------------------
# _resolve_catalogs
# ---------------------------------------------------------------------------


def test_resolve_catalogs_case_insensitive():
    valid, unknown = _resolve_catalogs(["pains", "Brenk"])
    assert valid == ["PAINS", "BRENK"]
    assert unknown == []


def test_resolve_catalogs_all_short_circuits():
    valid, unknown = _resolve_catalogs(["PAINS", "ALL", "BRENK"])
    assert valid == ["ALL"]
    assert unknown == []


def test_resolve_catalogs_unknown():
    valid, unknown = _resolve_catalogs(["PAINS", "BOGUS"])
    assert valid == ["PAINS"]
    assert unknown == ["BOGUS"]


def test_resolve_catalogs_dedup():
    valid, _ = _resolve_catalogs(["PAINS", "PAINS"])
    assert valid == ["PAINS"]


def test_default_catalogs_are_valid():
    valid, unknown = _resolve_catalogs(DEFAULT_CATALOGS)
    assert unknown == []
    assert set(valid) == {"PAINS", "BRENK"}


def test_all_catalog_names_present():
    for name in ["PAINS", "PAINS_A", "PAINS_B", "PAINS_C", "BRENK", "NIH", "ZINC", "CHEMBL", "ALL"]:
        assert name in CATALOG_NAMES


# ---------------------------------------------------------------------------
# smiles_to_mol
# ---------------------------------------------------------------------------


def test_smiles_to_mol_valid():
    assert smiles_to_mol("CCO") is not None


def test_smiles_to_mol_invalid():
    assert smiles_to_mol("not_a_smiles") is None


# ---------------------------------------------------------------------------
# screen_molecule
# ---------------------------------------------------------------------------


def test_caffeine_clean_under_default():
    valid, _ = _resolve_catalogs(DEFAULT_CATALOGS)
    from structure_alerts.checker import _REACTIVE_SMARTS, _build_catalog

    cat = _build_catalog(tuple(valid))
    alerts = screen_molecule(smiles_to_mol(CAFFEINE), cat, _REACTIVE_SMARTS)
    assert alerts == []


def test_catechol_flagged_as_pains():
    valid, _ = _resolve_catalogs(["PAINS"])
    from structure_alerts.checker import _build_catalog

    cat = _build_catalog(tuple(valid))
    alerts = screen_molecule(smiles_to_mol(CATECHOL), cat, [])
    assert len(alerts) >= 1
    assert all(a["category"] == "pains" for a in alerts)
    assert all(a["source"].upper().startswith("PAINS") for a in alerts)


# ---------------------------------------------------------------------------
# run  (batch API)
# ---------------------------------------------------------------------------


def test_run_caffeine_passes():
    result = run(_c(CAFFEINE, "caffeine"))
    assert result["count"] == 1
    assert result["passed"] == ["caffeine"]
    assert result["flagged"] == []
    assert result["results"][0]["id"] == "caffeine"
    assert result["results"][0]["passed"] is True
    assert result["results"][0]["num_alerts"] == 0


def test_run_catechol_flagged_with_reason():
    result = run(_c(CATECHOL, "catechol"))
    assert result["flagged"] == ["catechol"]
    rec = result["results"][0]
    assert rec["passed"] is False
    assert rec["num_alerts"] >= 1
    # every alert carries a human-readable reason
    assert all(a["description"] for a in rec["alerts"])


def test_run_reactive_group_flagged():
    result = run(_c(ACETYL_CHLORIDE, "acyl"), {"filter_catalogs": ["BRENK"]})
    assert result["flagged"] == ["acyl"]
    sources = {a["source"] for a in result["results"][0]["alerts"]}
    assert "reactive_smarts" in sources or any(s == "Brenk" for s in sources)


def test_run_michael_acceptor_flagged():
    result = run(_c(MICHAEL, "mvk"), {"filter_catalogs": ["BRENK"], "reactive_smarts": True})
    assert result["flagged"] == ["mvk"]


def test_run_invalid_smiles_in_errors():
    result = run(
        {"compounds": [{"smiles": CAFFEINE, "id": "good"}, {"smiles": "not_a_smiles", "id": "bad"}]}
    )
    assert result["errors"] == [{"id": "bad", "smiles": "not_a_smiles"}]
    assert result["count"] == 1
    assert result["summary"]["invalid"] == 1


def test_run_empty():
    result = run({"compounds": []})
    assert result["count"] == 0
    assert "error" in result


def test_run_missing_id_is_error():
    result = run({"compounds": [{"smiles": CAFFEINE}]})
    assert "error" in result
    assert "id" in result["error"]
    assert result["count"] == 0


def test_run_duplicate_id_is_error():
    result = run(
        {"compounds": [{"smiles": CAFFEINE, "id": "x"}, {"smiles": CATECHOL, "id": "x"}]}
    )
    assert "error" in result
    assert "unique" in result["error"]
    assert result["count"] == 0


def test_run_unknown_catalog_errors():
    result = run(_c(CAFFEINE, "c"), {"filter_catalogs": ["BOGUS"]})
    assert "error" in result
    assert result["count"] == 0


def test_run_catalogs_widen_results():
    """ALL should flag at least as many sources as PAINS+BRENK for catechol."""
    default = run(_c(CATECHOL, "c"))
    everything = run(_c(CATECHOL, "c"), {"filter_catalogs": ["ALL"], "reactive_smarts": False})
    assert everything["results"][0]["num_alerts"] >= default["results"][0]["num_alerts"]


def test_run_include_passing_false_omits_clean():
    result = run(
        {"compounds": [{"smiles": CAFFEINE, "id": "caffeine"}, {"smiles": CATECHOL, "id": "cat"}]},
        {"include_passing": False},
    )
    # caffeine clean -> excluded from results, but still counted in passed
    ids_in_results = {r["id"] for r in result["results"]}
    assert "caffeine" not in ids_in_results
    assert "cat" in ids_in_results
    assert result["passed"] == ["caffeine"]


def test_run_summary_by_source():
    result = run(_c(CATECHOL, "c"), {"filter_catalogs": ["PAINS"], "reactive_smarts": False})
    assert result["summary"]["flagged"] == 1
    assert sum(result["summary"]["by_source"].values()) == result["results"][0]["num_alerts"]


def test_run_smiles_list_key():
    # The platform auto-injects smiles_list_key = the input_schema array property.
    result = run(
        {"molecules": [{"smiles": CAFFEINE, "id": "c"}]}, {"smiles_list_key": "molecules"}
    )
    assert result["count"] == 1
    assert "error" not in result


def test_run_bare_list_input():
    # The platform delivers the parsed list directly as input_data (not wrapped).
    result = run([{"smiles": CAFFEINE, "id": "caffeine"}, {"smiles": CATECHOL, "id": "cat"}])
    assert result["count"] == 2
    assert result["passed"] == ["caffeine"]
    assert result["flagged"] == ["cat"]


def test_run_ignores_upload_descriptor_in_params():
    # Upload mode: params[key] is a file descriptor (dict), input_data[key] empty.
    # The descriptor must never be treated as the compound list.
    result = run(
        {"compounds": []},
        {"smiles_list_key": "compounds", "compounds": {"type": "upload", "storage_key": "x"}},
    )
    assert "error" in result
    assert result["count"] == 0


def test_run_params_used_passthrough():
    params = {"filter_catalogs": ["PAINS"], "reactive_smarts": False}
    result = run(_c(CAFFEINE, "c"), params)
    assert result["params_used"] == params


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_with_files(tmp_path):
    from structure_alerts.checker import main

    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps(
            {"compounds": [{"smiles": CAFFEINE, "id": "a"}, {"smiles": CATECHOL, "id": "b"}]}
        )
    )
    output_file = tmp_path / "output.json"
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps({"filter_catalogs": ["PAINS", "BRENK"]}))

    old_argv = sys.argv
    sys.argv = [
        "checker.py",
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
    assert data["count"] == 2
    assert data["summary"]["flagged"] == 1


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
