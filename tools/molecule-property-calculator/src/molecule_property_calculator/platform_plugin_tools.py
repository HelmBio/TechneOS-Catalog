"""Platform Assistant plugin — inline tool function injection.

This module is the single source for function(s) that the
``techneos.platform_assistant_tools`` entry point exports.  The agent-service
discovers these at startup via ``load_extra_platform_tools()`` and registers
them as inline Platform Assistant capabilities.

Keeping platform-tool functions in a dedicated module (separate from the
worker-dispatched ``calculator.py`` entry point) makes the boundary between
worker-side execution and agent-side inline execution explicit.
"""

from __future__ import annotations


async def calculate_molecule_properties(
    smiles: list[str],
    detailed: bool = False,
) -> dict:
    """Calculate molecular properties for a list of SMILES strings using RDKit.

    Use this tool when the user needs molecular descriptors, property
    calculations, or ADME-related properties for chemical compounds.
    Returns properties such as molecular weight, LogP, HBD, HBA, TPSA,
    rotatable bonds, aromatic rings, and molecular formula.

    Args:
        smiles: List of SMILES strings to calculate properties for.
            Each entry can be a plain SMILES string or an object
            ``{"smiles": "...", "id": "..."}`` for tracking.
        detailed: Include extra per-molecule info (num_atoms, num_bonds).

    Returns:
        A dict with:
            - results: List of per-molecule property dictionaries.
            - errors: List of invalid entries.
            - count: Number of successfully processed molecules.
            - params_used: The parameters that were applied.
    """
    from molecule_property_calculator.calculator import run

    return run({"smiles": smiles}, {"detailed": detailed})


# Convenience list for ToolRegistry registration loops.
PLATFORM_PLUGIN_TOOLS = [
    calculate_molecule_properties,
]
