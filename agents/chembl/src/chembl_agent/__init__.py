"""ChEMBL Research Assistant agent package.

The agent-service discovers this package via the ``techneos.agents`` Python
entry point declared in ``pyproject.toml`` and reads ``CHEMBL_TOOLS``
(re-exported below) to register the tool callables with the global
``ToolRegistry``. No import-time side effects — the registration is
performed by the runtime, not by this module's import.

This shape lets chembl-agent ship as a normal pip-installable wheel
that doesn't depend on ``core``'s tool_registry implementation: the
agent-service is the one component that imports both ``core`` and
this package, so the coupling lives there instead of here.
"""

from chembl_agent.tools import CHEMBL_TOOLS

__all__ = ["CHEMBL_TOOLS"]
