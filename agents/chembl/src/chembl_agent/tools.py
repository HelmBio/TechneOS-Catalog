"""ChEMBL REST API tools for drug discovery agents.

Each function is a standalone async tool designed to be used with PydanticAI.
PydanticAI auto-generates function-calling schemas from the type hints and
docstrings, so no manual JSON schema definitions are needed.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

CHEMBL_BASE_URL = "https://www.ebi.ac.uk/chembl/api/data"
_TIMEOUT = 30.0


async def _chembl_get(path: str, params: dict | None = None) -> dict:
    """Make a GET request to the ChEMBL REST API."""
    url = f"{CHEMBL_BASE_URL}{path}"
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def chembl_search_compounds(query: str, limit: int = 10) -> dict:
    """Search ChEMBL for compounds matching a free-text query.

    Use this tool when the user asks about a drug, compound, molecule, or
    chemical substance by name, synonym, or partial name.

    Args:
        query: Search term — compound name, synonym, or keyword (e.g. "aspirin", "ibuprofen").
        limit: Maximum number of results to return. Defaults to 10.

    Returns:
        A dict with a ``compounds`` list. Each entry contains chembl_id,
        pref_name, molecule_type, max_phase, and molecule_structures (SMILES).
    """
    try:
        data = await _chembl_get(
            "/molecule/search.json",
            params={"q": query, "limit": limit},
        )
        molecules = data.get("molecules", [])
        results = []
        for mol in molecules[:limit]:
            structures = mol.get("molecule_structures") or {}
            results.append(
                {
                    "chembl_id": mol.get("molecule_chembl_id"),
                    "pref_name": mol.get("pref_name"),
                    "molecule_type": mol.get("molecule_type"),
                    "max_phase": mol.get("max_phase"),
                    "smiles": structures.get("canonical_smiles"),
                }
            )
        return {"compounds": results, "total": len(results)}
    except httpx.HTTPStatusError as exc:
        logger.warning("ChEMBL search_compounds failed: %s", exc)
        return {"error": f"ChEMBL API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("ChEMBL search_compounds request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def chembl_get_compound(chembl_id: str) -> dict:
    """Get detailed information about a specific compound by its ChEMBL ID.

    Use this tool when the user provides a ChEMBL compound identifier
    (e.g. CHEMBL25) and wants detailed properties.

    Args:
        chembl_id: The ChEMBL compound identifier (e.g. "CHEMBL25").

    Returns:
        A dict with compound properties: chembl_id, pref_name, molecule_type,
        max_phase, SMILES, InChI key, molecular weight, ALogP, hydrogen bond
        acceptors/donors, polar surface area, and Lipinski Ro5 violations.
    """
    try:
        mol = await _chembl_get(f"/molecule/{chembl_id}.json")
        structures = mol.get("molecule_structures") or {}
        props = mol.get("molecule_properties") or {}
        return {
            "chembl_id": mol.get("molecule_chembl_id"),
            "pref_name": mol.get("pref_name"),
            "molecule_type": mol.get("molecule_type"),
            "max_phase": mol.get("max_phase"),
            "smiles": structures.get("canonical_smiles"),
            "inchi_key": structures.get("standard_inchi_key"),
            "molecular_weight": props.get("full_mwt"),
            "alogp": props.get("alogp"),
            "hba": props.get("hba"),
            "hbd": props.get("hbd"),
            "psa": props.get("psa"),
            "ro5_violations": props.get("num_ro5_violations"),
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("ChEMBL get_compound failed: %s", exc)
        return {"error": f"ChEMBL API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("ChEMBL get_compound request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def chembl_get_bioactivities(chembl_id: str, limit: int = 25) -> dict:
    """Get bioactivity data (assay results) for a compound.

    Use this tool when the user wants to know about a compound's biological
    activity, potency, IC50 values, or assay results.

    Args:
        chembl_id: The ChEMBL compound identifier (e.g. "CHEMBL25").
        limit: Maximum number of bioactivity records to return. Defaults to 25.

    Returns:
        A dict with a ``bioactivities`` list containing target info,
        activity type, value, units, pChEMBL value, and assay details.
    """
    try:
        data = await _chembl_get(
            "/activity.json",
            params={"molecule_chembl_id": chembl_id, "limit": limit},
        )
        activities = data.get("activities", [])
        results = []
        for act in activities[:limit]:
            results.append(
                {
                    "target_chembl_id": act.get("target_chembl_id"),
                    "target_pref_name": act.get("target_pref_name"),
                    "target_organism": act.get("target_organism"),
                    "standard_type": act.get("standard_type"),
                    "standard_value": act.get("standard_value"),
                    "standard_units": act.get("standard_units"),
                    "pchembl_value": act.get("pchembl_value"),
                    "assay_chembl_id": act.get("assay_chembl_id"),
                    "assay_type": act.get("assay_type"),
                }
            )
        return {"bioactivities": results, "total": len(results)}
    except httpx.HTTPStatusError as exc:
        logger.warning("ChEMBL get_bioactivities failed: %s", exc)
        return {"error": f"ChEMBL API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("ChEMBL get_bioactivities request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def chembl_search_targets(query: str, limit: int = 10) -> dict:
    """Search ChEMBL for drug targets matching a free-text query.

    Use this tool when the user asks about biological targets, proteins,
    receptors, enzymes, or gene products.

    Args:
        query: Target name, gene symbol, or keyword (e.g. "EGFR", "cyclooxygenase").
        limit: Maximum number of results to return. Defaults to 10.

    Returns:
        A dict with a ``targets`` list containing target_chembl_id,
        pref_name, target_type, and organism.
    """
    try:
        data = await _chembl_get(
            "/target/search.json",
            params={"q": query, "limit": limit},
        )
        targets = data.get("targets", [])
        results = []
        for t in targets[:limit]:
            results.append(
                {
                    "target_chembl_id": t.get("target_chembl_id"),
                    "pref_name": t.get("pref_name"),
                    "target_type": t.get("target_type"),
                    "organism": t.get("organism"),
                }
            )
        return {"targets": results, "total": len(results)}
    except httpx.HTTPStatusError as exc:
        logger.warning("ChEMBL search_targets failed: %s", exc)
        return {"error": f"ChEMBL API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("ChEMBL search_targets request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


async def chembl_get_target(chembl_id: str) -> dict:
    """Get detailed information about a specific target by its ChEMBL ID.

    Use this tool when the user provides a ChEMBL target identifier
    (e.g. CHEMBL2111389) and wants detailed information.

    Args:
        chembl_id: The ChEMBL target identifier (e.g. "CHEMBL2111389").

    Returns:
        A dict with target properties: target_chembl_id, pref_name,
        target_type, organism, tax_id, and component details (accession,
        description).
    """
    try:
        t = await _chembl_get(f"/target/{chembl_id}.json")
        components = []
        for comp in t.get("target_components", []):
            components.append(
                {
                    "accession": comp.get("accession"),
                    "description": comp.get("component_description"),
                }
            )
        return {
            "target_chembl_id": t.get("target_chembl_id"),
            "pref_name": t.get("pref_name"),
            "target_type": t.get("target_type"),
            "organism": t.get("organism"),
            "tax_id": t.get("tax_id"),
            "components": components,
        }
    except httpx.HTTPStatusError as exc:
        logger.warning("ChEMBL get_target failed: %s", exc)
        return {"error": f"ChEMBL API error: {exc.response.status_code}"}
    except httpx.RequestError as exc:
        logger.warning("ChEMBL get_target request error: %s", exc)
        return {"error": f"Request failed: {exc}"}


CHEMBL_TOOLS = [
    chembl_search_compounds,
    chembl_get_compound,
    chembl_get_bioactivities,
    chembl_search_targets,
    chembl_get_target,
]
