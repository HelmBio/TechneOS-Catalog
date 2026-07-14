"""Tests for ChEMBL tool functions.

All tests mock httpx to avoid hitting the real ChEMBL API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from chembl_agent.tools import (
    CHEMBL_TOOLS,
    chembl_get_bioactivities,
    chembl_get_compound,
    chembl_get_target,
    chembl_search_compounds,
    chembl_search_targets,
)


def _mock_response(data: dict, status_code: int = 200) -> httpx.Response:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    return resp


@pytest.fixture
def mock_httpx_client():
    """Patch httpx.AsyncClient so all tools use a mock transport."""
    mock_client = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("chembl_agent.tools.httpx.AsyncClient", return_value=ctx):
        yield mock_client


# ---------------------------------------------------------------------------
# chembl_search_compounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_compounds_success(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response(
        {
            "molecules": [
                {
                    "molecule_chembl_id": "CHEMBL25",
                    "pref_name": "ASPIRIN",
                    "molecule_type": "Small molecule",
                    "max_phase": 4,
                    "molecule_structures": {"canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O"},
                }
            ]
        }
    )

    result = await chembl_search_compounds("aspirin")

    assert result["total"] == 1
    assert result["compounds"][0]["chembl_id"] == "CHEMBL25"
    assert result["compounds"][0]["pref_name"] == "ASPIRIN"
    assert result["compounds"][0]["smiles"] == "CC(=O)Oc1ccccc1C(=O)O"


@pytest.mark.asyncio
async def test_search_compounds_empty(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response({"molecules": []})

    result = await chembl_search_compounds("nonexistent_compound_xyz")

    assert result["total"] == 0
    assert result["compounds"] == []


@pytest.mark.asyncio
async def test_search_compounds_api_error(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response({}, status_code=500)

    result = await chembl_search_compounds("aspirin")

    assert "error" in result


# ---------------------------------------------------------------------------
# chembl_get_compound
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_compound_success(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response(
        {
            "molecule_chembl_id": "CHEMBL25",
            "pref_name": "ASPIRIN",
            "molecule_type": "Small molecule",
            "max_phase": 4,
            "molecule_structures": {
                "canonical_smiles": "CC(=O)Oc1ccccc1C(=O)O",
                "standard_inchi_key": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            },
            "molecule_properties": {
                "full_mwt": "180.16",
                "alogp": "1.31",
                "hba": 3,
                "hbd": 1,
                "psa": "63.60",
                "num_ro5_violations": 0,
            },
        }
    )

    result = await chembl_get_compound("CHEMBL25")

    assert result["chembl_id"] == "CHEMBL25"
    assert result["molecular_weight"] == "180.16"
    assert result["ro5_violations"] == 0
    assert result["inchi_key"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"


@pytest.mark.asyncio
async def test_get_compound_not_found(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response({}, status_code=404)

    result = await chembl_get_compound("CHEMBL_INVALID")

    assert "error" in result


# ---------------------------------------------------------------------------
# chembl_get_bioactivities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_bioactivities_success(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response(
        {
            "activities": [
                {
                    "target_chembl_id": "CHEMBL2111389",
                    "target_pref_name": "Cyclooxygenase-2",
                    "target_organism": "Homo sapiens",
                    "standard_type": "IC50",
                    "standard_value": "100",
                    "standard_units": "nM",
                    "pchembl_value": "7.0",
                    "assay_chembl_id": "CHEMBL12345",
                    "assay_type": "B",
                }
            ]
        }
    )

    result = await chembl_get_bioactivities("CHEMBL25")

    assert result["total"] == 1
    bio = result["bioactivities"][0]
    assert bio["target_pref_name"] == "Cyclooxygenase-2"
    assert bio["standard_type"] == "IC50"
    assert bio["pchembl_value"] == "7.0"


# ---------------------------------------------------------------------------
# chembl_search_targets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_targets_success(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response(
        {
            "targets": [
                {
                    "target_chembl_id": "CHEMBL2111389",
                    "pref_name": "Cyclooxygenase-2",
                    "target_type": "SINGLE PROTEIN",
                    "organism": "Homo sapiens",
                }
            ]
        }
    )

    result = await chembl_search_targets("COX-2")

    assert result["total"] == 1
    assert result["targets"][0]["pref_name"] == "Cyclooxygenase-2"


# ---------------------------------------------------------------------------
# chembl_get_target
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_target_success(mock_httpx_client: AsyncMock) -> None:
    mock_httpx_client.get.return_value = _mock_response(
        {
            "target_chembl_id": "CHEMBL2111389",
            "pref_name": "Cyclooxygenase-2",
            "target_type": "SINGLE PROTEIN",
            "organism": "Homo sapiens",
            "tax_id": 9606,
            "target_components": [
                {
                    "accession": "P35354",
                    "component_description": "Prostaglandin G/H synthase 2",
                }
            ],
        }
    )

    result = await chembl_get_target("CHEMBL2111389")

    assert result["target_chembl_id"] == "CHEMBL2111389"
    assert result["organism"] == "Homo sapiens"
    assert len(result["components"]) == 1
    assert result["components"][0]["accession"] == "P35354"


# ---------------------------------------------------------------------------
# Tool registry checks
# ---------------------------------------------------------------------------


def test_all_tools_registered() -> None:
    """All five ChEMBL tools are in the CHEMBL_TOOLS list."""
    names = {fn.__name__ for fn in CHEMBL_TOOLS}
    assert names == {
        "chembl_search_compounds",
        "chembl_get_compound",
        "chembl_get_bioactivities",
        "chembl_search_targets",
        "chembl_get_target",
    }


def test_tools_are_async() -> None:
    """All ChEMBL tools are async functions."""
    import asyncio

    for fn in CHEMBL_TOOLS:
        assert asyncio.iscoroutinefunction(fn), f"{fn.__name__} should be async"


def test_tools_have_docstrings() -> None:
    """All ChEMBL tools have docstrings (required for PydanticAI schema generation)."""
    for fn in CHEMBL_TOOLS:
        assert fn.__doc__, f"{fn.__name__} is missing a docstring"
