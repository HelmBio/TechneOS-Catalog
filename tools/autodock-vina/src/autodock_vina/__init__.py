"""AutoDock Vina docking tool for the TechneOS platform.

Docks a list of ligands (the representative molecules of a hit set) into a
prepared protein receptor with AutoDock Vina and ranks them by predicted
binding affinity. See ``docking.py`` for the ``run(inputs, params)`` contract.
"""

from autodock_vina.docking import run

__all__ = ["run"]
__version__ = "0.1.0"
