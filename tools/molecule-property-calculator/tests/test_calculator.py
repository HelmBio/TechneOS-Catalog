"""Tests for molecule-property-calculator (RDKit-based).

Runs standalone (no pytest required):
    python test_calculator.py
    python test_calculator.py -v

Also works with pytest:
    uv run pytest tools/molecule-property-calculator/tests
"""

import json
import os
import sys
import traceback

# Allow importing from the package when run standalone
_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(_pkg_dir, "src")
_tool_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _tool_dir not in sys.path:
    sys.path.insert(0, _tool_dir)

# Import from the package, falling back to standalone tool.py for sandbox validation
try:
    from molecule_property_calculator.calculator import (
        PROPERTY_MAP,
        _normalize_input_item,
        calculate_properties,
        run,
        smiles_to_mol,
    )
except ImportError:
    from tool import (  # type: ignore[import-untyped]
        PROPERTY_MAP,
        _normalize_input_item,
        calculate_properties,
        run,
        smiles_to_mol,
    )

# ---------------------------------------------------------------------------
# _normalize_input_item
# ---------------------------------------------------------------------------


def test_normalize_plain_string():
    assert _normalize_input_item("CCO") == ("CCO", None)


def test_normalize_dict_with_id():
    assert _normalize_input_item({"smiles": "CCO", "id": "mol-1"}) == ("CCO", "mol-1")


def test_normalize_dict_without_id():
    assert _normalize_input_item({"smiles": "c1ccccc1"}) == ("c1ccccc1", None)


def test_normalize_dict_missing_smiles():
    assert _normalize_input_item({"id": "x"}) == ("", "x")


def test_normalize_empty_string():
    assert _normalize_input_item("") == ("", None)


# ---------------------------------------------------------------------------
# smiles_to_mol
# ---------------------------------------------------------------------------


def test_smiles_to_mol_valid():
    mol = smiles_to_mol("CCO")
    assert mol is not None
    assert mol.GetNumAtoms() == 3


def test_smiles_to_mol_invalid():
    assert smiles_to_mol("not-a-smiles") is None


def test_smiles_to_mol_caching():
    mol1 = smiles_to_mol("c1ccccc1")
    mol2 = smiles_to_mol("c1ccccc1")
    assert mol1 is mol2


# ---------------------------------------------------------------------------
# calculate_properties  (single SMILES)
# ---------------------------------------------------------------------------


def test_calculate_properties_valid():
    props = calculate_properties("CCO")
    assert props is not None
    assert props["valid"] is True
    assert props["smiles"] == "CCO"
    assert props["hbd"] == 1
    assert props["hba"] == 1


def test_calculate_properties_invalid():
    assert calculate_properties("invalid") is None


def test_calculate_properties_detailed():
    props = calculate_properties("CCO", detailed=True)
    assert props is not None
    assert "num_atoms" in props
    assert "num_bonds" in props
    assert props["num_atoms"] == 3


def test_calculate_properties_ethanol_mw():
    props = calculate_properties("CCO")
    assert props is not None
    assert abs(props["mw"] - 46.068) < 0.01


def test_calculate_properties_benzene():
    props = calculate_properties("c1ccccc1")
    assert props is not None
    assert props["aromatic_rings"] == 1
    assert props["hbd"] == 0
    assert props["formula"] == "C6H6"


def test_calculate_properties_all_keys_present():
    props = calculate_properties("CCO")
    assert props is not None
    for key in PROPERTY_MAP:
        assert key in props


def test_calculate_properties_float_rounding():
    props = calculate_properties("CCO")
    assert props is not None
    for key, val in props.items():
        if isinstance(val, float):
            s = str(val)
            if "." in s:
                decimals = len(s.split(".")[1])
                assert decimals <= 3


# ---------------------------------------------------------------------------
# run  (batch API)
# ---------------------------------------------------------------------------


def test_run_simple():
    result = run({"smiles": ["CCO", "c1ccccc1"]})
    assert result["count"] == 2
    assert len(result["results"]) == 2
    assert len(result["errors"]) == 0


def test_run_empty():
    result = run({"smiles": []})
    assert result["count"] == 0
    assert result["results"] == []
    assert "error" in result


def test_run_missing_key():
    result = run({})
    assert result["count"] == 0
    assert "error" in result


def test_run_mixed_valid_invalid():
    result = run({"smiles": ["CCO", "not-valid", "c1ccccc1"]})
    assert result["count"] == 2
    assert len(result["errors"]) == 1
    assert result["errors"][0] == "not-valid"


def test_run_with_ids():
    result = run(
        {
            "smiles": [
                {"smiles": "CCO", "id": "mol-1"},
                {"smiles": "c1ccccc1", "id": "mol-2"},
            ]
        }
    )
    assert result["count"] == 2
    assert result["results"][0]["id"] == "mol-1"
    assert result["results"][1]["id"] == "mol-2"


def test_run_params():
    result = run({"smiles": ["CCO"]}, {"detailed": True})
    assert result["params_used"] == {"detailed": True}


def test_run_smiles_list_key():
    result = run({"compounds": ["CCO", "c1ccccc1"]}, {"smiles_list_key": "compounds"})
    assert result["count"] == 2
    assert "error" not in result


def test_run_smiles_list_key_default_fallback():
    """Without smiles_list_key, it should still read from 'smiles'."""
    result = run({"smiles": ["CCO"]})
    assert result["count"] == 1
    assert "error" not in result


def test_run_detailed():
    result = run({"smiles": ["CCO"]}, {"detailed": True})
    assert result["count"] == 1
    assert "num_atoms" in result["results"][0]


def test_run_mixed_input_types():
    result = run({"smiles": ["CCO", {"smiles": "c1ccccc1", "id": "benzene"}]})
    assert result["count"] == 2
    assert result["results"][0].get("id") is None
    assert result["results"][1].get("id") == "benzene"


def test_run_property_map_keys():
    expected_keys = {
        "mw",
        "logp",
        "hbd",
        "hba",
        "tpsa",
        "rotatable_bonds",
        "heavy_atom_count",
        "aromatic_rings",
        "aliphatic_rings",
        "hba_lipinski",
        "hbd_lipinski",
        "fraction_sp3",
        "num_rings",
        "num_heteroatoms",
        "num_saturated_rings",
    }
    assert set(PROPERTY_MAP.keys()) == expected_keys


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_with_files(tmp_path):
    from molecule_property_calculator.calculator import main

    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"smiles": ["CCO", "c1ccccc1"]}))

    output_file = tmp_path / "output.json"
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps({"detailed": True}))

    old_argv = sys.argv
    sys.argv = [
        "calculator.py",
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
    assert data["params_used"] == {"detailed": True}


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
            # pytest fixtures (tmp_path) won't work standalone — skip those
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
