"""Dataset profiler for the TechneOS platform.

Summarises any tabular dataset (CSV/TSV/JSON) into an HTML or PDF report with a
preview table and per-column distribution / heatmap plots.

Public surface:

    from dataset_profiler import run
    result = run(
        {"dataset_file": "/work/input/data.csv"},
        {"format": "pdf", "include_plots": True, "title": "Data Summary"},
    )

The container entry point is `dataset_profiler.core:run` (set via
ENTRYPOINT_SPEC in the Dockerfile). `dataset_profiler.core:parse` is a
pass-through input hook the runtime calls before `run` — see core.py.
"""

from dataset_profiler.core import parse, run

__all__ = ["parse", "run"]
__version__ = "0.1.0"
