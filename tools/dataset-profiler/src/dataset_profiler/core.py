"""Dataset profiler — `run(inputs, params) -> dict` contract.

Summarises one or more **tabular datasets** (CSV, TSV, or JSON), renders a
Jinja-templated HTML report with a preview table and (optionally) per-column
distribution histograms or a sample x metric heatmap, and emits the final
report as either HTML or PDF (via WeasyPrint). It is domain-agnostic: any
tabular data works, not just chemistry predictions.

The tool runs in two modes, transparently:
    * **Pipeline** — the worker hands paths via `inputs["upstream"]` (a dict
      keyed by upstream step) plus a convenience `inputs["upstream_csvs"]`
      (the CSV/TSV subset). These are raw `/work/...` paths.
    * **Standalone** — a user-uploaded/pasted/dataset file arrives as a
      `inputs["{field}_file"]` path (e.g. `dataset_file`). Because we export a
      pass-through `parse()` below, the runtime hands us the raw path instead
      of pre-parsing it as a SMILES list.

`run()` gathers table paths from both shapes (see `_gather_table_paths`).

Contract:
    inputs:
        {field}_file: str
            Standalone uploads — any key ending in `_file` is treated as a
            table path (e.g. `dataset_file`).
        upstream: dict[str, list[str]] (optional)
            Pipeline upstream artifacts, keyed by step name.
        upstream_csvs / upstream_tables: list[str] (optional)
            Flat lists of upstream table paths.
        input_dir: str (optional)
            Legacy fallback: scanned recursively for *.csv / *.tsv / *.json.
    params:
        format: "pdf" | "html" (default "pdf")
        include_plots: bool (default True)
        title: str (default "Data Summary Report")
        input_format: "auto" | "csv" | "tsv" | "json" (default "auto")
            Force a reader; "auto" infers from file suffix / content-type.
        plot_type: "histogram" | "heatmap" (default "histogram")
            "histogram" plots each numeric column's distribution. "heatmap"
            renders a single rows=samples x cols=numeric heatmap, with rows
            labelled by the first non-numeric column (e.g. an id) and each
            column normalised independently; it falls back to histograms when
            the table has too many rows to label legibly.
    returns:
        {
            "report_file": "report.pdf" | "report.html",
            "format": "pdf" | "html",
            "n_rows": int,
            "numeric_columns": list[str],   # numeric columns that became plots
            "plots": list[str],             # plot filenames (empty if include_plots=False)
        }

Side-effect artifacts (written via techneos-tool-runtime helpers):
    report.{pdf,html}    – the rendered report
    plot_{column}.png    – one histogram per numeric column (histogram mode)
    heatmap.png          – one sample x metric heatmap (heatmap mode)

The returned dict is persisted by the runtime as /work/output/result.json, so
the tool does not write its own metadata file.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from jinja2 import Template

from techneos_tool_runtime import artifact_path, write_artifact

logger = logging.getLogger(__name__)


_DEFAULT_TITLE = "Data Summary Report"
_ID_COLUMNS = frozenset({"smiles", "name", "id", "molecule", "mol_id", "index"})

# Tabular file suffixes we know how to read. Used both for auto-detection and
# to filter upstream artifacts (an upstream step may also emit .png/.pdf etc.).
_TABLE_SUFFIXES = frozenset({".csv", ".tsv", ".json"})

# Above this row count, a per-sample heatmap has too many rows to label
# legibly, so `plot_type="heatmap"` falls back to distribution histograms.
_HEATMAP_ROW_CAP = 50

# Annotate heatmap cells with raw values only while the grid stays readable.
_HEATMAP_ANNOTATE_CELLS = 200

# Plots are embedded as base64 data URIs (see _data_uri) so the HTML report is
# self-contained — it renders in the portal artifact viewer and when downloaded,
# not only when opened beside the sibling PNG files.
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{{ title }}</title>
<style>
  @page { size: A4; margin: 1.2cm; }
  body { font-family: sans-serif; margin: 0; color: #222; }
  h1 { color: #333; font-size: 1.5em; margin: 0 0 0.2em; }
  h2 { font-size: 1.1em; margin: 0.7em 0 0.3em; }
  p { margin: 0.15em 0; }
  table { border-collapse: collapse; width: 100%; margin: 0.4em 0; font-size: 0.85em; page-break-inside: avoid; }
  th, td { border: 1px solid #ccc; padding: 0.25em 0.6em; text-align: left; }
  th { background: #f5f5f5; }
  /* One plot (e.g. a heatmap) spans the width; multiple plots pack two-up so
     histograms don't each claim a full row of vertical space. */
  .plots img { max-width: 100%; margin: 0.3em 0; page-break-inside: avoid; }
  .plots.grid img { width: 49%; margin: 0 0.5% 0.3em 0; vertical-align: top; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<h2>Summary</h2>
<p>Total rows: {{ n_rows }}</p>
<p>Numeric columns: {{ numeric_columns }}</p>

<h2>Results Table</h2>
{{ table_html }}

{% if plot_images %}
<h2>Plots</h2>
<div class="plots{% if plots_grid %} grid{% endif %}">
{% for img in plot_images %}
<img src="{{ img }}" alt="plot">
{% endfor %}
</div>
{% endif %}
</body>
</html>
"""


def parse(file_path: str, params: dict) -> str:  # noqa: ARG001
    """Pass-through input hook for the techneos-tool-runtime preprocessor.

    The runtime parses every ``{field}_file`` input before calling ``run()``,
    defaulting to the SMILES-list parser when a tool declares no ``input_kind``.
    That default is wrong for a generic tabular tool — it would coerce an
    arbitrary table into ``[{smiles, id}]`` (or fail). Exporting this function
    next to ``run`` overrides that behaviour: we return the path unchanged so
    ``run()`` receives the raw file and reads it itself, supporting any of our
    tabular formats (CSV/TSV/JSON). See ``techneos_tool_runtime.runner``.
    """
    return file_path


def _gather_table_paths(inputs: dict) -> list[Path]:
    """Resolve the table paths to read, across both execution modes.

    Sources, in order (de-duplicated, first occurrence wins):
        1. Standalone uploads — any ``inputs["{field}_file"]`` string path
           (e.g. ``dataset_file``). The runtime leaves these as paths thanks
           to the pass-through ``parse()`` above.
        2. Pipeline upstream — ``inputs["upstream"]`` (dict step -> [paths]),
           filtered to known tabular suffixes.
        3. Legacy flat lists — ``inputs["upstream_csvs"]`` /
           ``inputs["upstream_tables"]``.
        4. Legacy fallback — ``inputs["input_dir"]`` scanned recursively for
           *.csv / *.tsv / *.json.
    """
    paths: list[Path] = []

    def _add(p: str | Path) -> None:
        path = Path(p)
        if path not in paths:
            paths.append(path)

    # 1. Standalone uploaded/pasted/dataset files.
    for key, value in inputs.items():
        if key.endswith("_file") and isinstance(value, str):
            _add(value)

    # 2. Pipeline upstream artifacts (dict keyed by step name).
    upstream = inputs.get("upstream") or {}
    if isinstance(upstream, dict):
        for step_paths in upstream.values():
            for p in step_paths or []:
                if Path(p).suffix.lower() in _TABLE_SUFFIXES:
                    _add(p)

    # 3. Legacy flat lists.
    for list_key in ("upstream_csvs", "upstream_tables"):
        for p in inputs.get(list_key) or []:
            _add(p)

    if paths:
        return paths

    # 4. Legacy directory scan.
    input_dir = inputs.get("input_dir")
    if input_dir:
        for suffix in sorted(_TABLE_SUFFIXES):
            for p in sorted(Path(input_dir).rglob(f"*{suffix}")):
                _add(p)

    return paths


def _read_table(path: Path, input_format: str = "auto") -> pd.DataFrame:
    """Read one tabular file (CSV / TSV / JSON) into a DataFrame.

    ``input_format`` of ``"auto"`` infers the reader from the file suffix;
    pass ``"csv"`` / ``"tsv"`` / ``"json"`` to force one (useful when an
    uploaded file has a missing or misleading extension).
    """
    fmt = (input_format or "auto").lower()
    if fmt == "auto":
        suffix = path.suffix.lower()
        fmt = {".csv": "csv", ".tsv": "tsv", ".json": "json"}.get(suffix, "csv")

    if fmt == "csv":
        return pd.read_csv(path)
    if fmt == "tsv":
        return pd.read_csv(path, sep="\t")
    if fmt == "json":
        # `pd.read_json` handles a JSON array of records or column-oriented
        # objects; json_normalize flattens nested records when needed.
        data = json.loads(Path(path).read_text())
        if isinstance(data, list):
            return pd.json_normalize(data)
        return pd.json_normalize(data) if isinstance(data, dict) else pd.read_json(path)
    raise ValueError(f"Unsupported input_format {fmt!r} (expected csv, tsv, or json)")


def _coerce_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(raw)


def _identify_numeric_columns(df: pd.DataFrame) -> list[str]:
    """Numeric (non-boolean) columns that aren't identifiers — these get plotted.

    Booleans pass is_numeric_dtype but histogramming them produces a meaningless
    two-bar chart and, on numpy>=2, breaks outright (boolean subtraction is no
    longer allowed). Treat them as flags, not data columns.
    """
    return [
        c
        for c in df.columns
        if c.lower() not in _ID_COLUMNS
        and pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_bool_dtype(df[c])
    ]


def _identify_label_column(df: pd.DataFrame) -> str | None:
    """The first non-numeric, non-boolean column — used as the x-axis labels in
    bar plots (e.g. an id/name column). Returns None to fall back to the row
    index when every column is numeric."""
    for c in df.columns:
        if not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]):
            return c
    return None


def _render_plots(
    df: pd.DataFrame,
    numeric_cols: list[str],
    *,
    plot_type: str = "histogram",
    label_col: str | None = None,
) -> list[str]:
    """Render the plot artifacts and return their filenames.

    ``plot_type="histogram"`` (default) writes one ``plot_{col}.png`` per
    numeric column. ``plot_type="heatmap"`` writes a single ``heatmap.png``
    with rows=samples (labelled by ``label_col`` / the row index) and
    cols=numeric, each column normalised independently. Heatmaps are
    unreadable for large tables, so they fall back to histograms beyond
    ``_HEATMAP_ROW_CAP``.
    """
    if plot_type == "heatmap":
        if len(df) <= _HEATMAP_ROW_CAP:
            return [_render_heatmap(df, numeric_cols, label_col)]
        logger.info(
            "plot_type='heatmap' but %d rows exceed the %d-row cap — using histograms",
            len(df),
            _HEATMAP_ROW_CAP,
        )
    return _render_histograms(df, numeric_cols)


def _render_histograms(df: pd.DataFrame, numeric_cols: list[str]) -> list[str]:
    """One distribution histogram per numeric column."""
    plot_filenames: list[str] = []
    for col in numeric_cols:
        fig, ax = plt.subplots(figsize=(6, 3))
        df[col].dropna().hist(ax=ax, bins=30, edgecolor="black", alpha=0.7)
        ax.set_title(col)
        ax.set_xlabel(col)
        ax.set_ylabel("Count")
        fig.tight_layout()
        fname = f"plot_{col}.png"
        fig.savefig(artifact_path(fname), dpi=100, bbox_inches="tight")
        plt.close(fig)
        plot_filenames.append(fname)
    return plot_filenames


def _render_heatmap(
    df: pd.DataFrame, numeric_cols: list[str], label_col: str | None
) -> str:
    """A single rows=samples x cols=numeric heatmap, written to heatmap.png.

    Each column is min-max normalised on its own so the colour scale isn't
    dominated by a large-magnitude column; cells are annotated with the raw
    value while the grid stays small enough to read.
    """
    labels = (
        df[label_col].astype(str).tolist()
        if label_col is not None
        else [str(i) for i in range(len(df))]
    )
    data = df[numeric_cols].to_numpy(dtype=float)  # rows x cols

    # Per-column min-max → [0, 1]; constant (or all-NaN) columns map to 0.5.
    col_min = np.nanmin(data, axis=0)
    col_max = np.nanmax(data, axis=0)
    span = col_max - col_min
    with np.errstate(invalid="ignore"):
        norm = np.where(span > 0, (data - col_min) / np.where(span > 0, span, 1.0), 0.5)

    fig_w = min(16.0, max(6.0, len(numeric_cols) * 1.2 + 2.0))
    fig_h = min(16.0, max(3.0, len(labels) * 0.4 + 1.5))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(norm, aspect="auto", cmap="viridis", vmin=0.0, vmax=1.0)

    ax.set_xticks(range(len(numeric_cols)))
    ax.set_xticklabels(numeric_cols, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("metric")
    ax.set_ylabel(label_col or "row")

    if len(labels) * len(numeric_cols) <= _HEATMAP_ANNOTATE_CELLS:
        for i in range(len(labels)):
            for j in range(len(numeric_cols)):
                val = data[i, j]
                if not np.isnan(val):
                    ax.text(
                        j, i, f"{val:g}",
                        ha="center", va="center", fontsize=8,
                        color="white" if norm[i, j] < 0.5 else "black",
                    )

    fig.colorbar(im, ax=ax, label="per-column normalised")
    fig.tight_layout()
    fname = "heatmap.png"
    fig.savefig(artifact_path(fname), dpi=100, bbox_inches="tight")
    plt.close(fig)
    return fname


def _data_uri(filename: str) -> str:
    """Read a written PNG artifact and return it as a base64 ``data:`` URI.

    Embedding the image inline keeps the HTML report self-contained: it renders
    wherever the file is served (the portal artifact viewer, a download, email),
    not only when opened in the same directory as the sibling PNG files.
    """
    raw = Path(artifact_path(filename)).read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _render_html(
    *,
    title: str,
    n_rows: int,
    numeric_cols: list[str],
    table_html: str,
    plot_images: list[str],
    include_plots: bool,
) -> str:
    images = plot_images if include_plots else []
    template = Template(_HTML_TEMPLATE)
    return template.render(
        title=title,
        n_rows=n_rows,
        numeric_columns=", ".join(numeric_cols) if numeric_cols else "N/A",
        table_html=table_html,
        plot_images=images,
        # Pack multiple plots two-up; a lone plot (heatmap) stays full width.
        plots_grid=len(images) > 1,
    )


def run(inputs: dict, params: dict) -> dict:
    """Entry point invoked by the runtime. See module docstring for the contract."""
    inputs = inputs or {}
    params = params or {}

    fmt = str(params.get("format") or "pdf").lower()
    if fmt not in {"pdf", "html"}:
        raise ValueError(f"`format` must be 'pdf' or 'html', got {fmt!r}")
    include_plots = _coerce_bool(params.get("include_plots"), default=True)
    title = str(params.get("title") or _DEFAULT_TITLE)
    input_format = str(params.get("input_format") or "auto").lower()
    plot_type = str(params.get("plot_type") or "histogram").lower()
    if plot_type not in {"histogram", "heatmap"}:
        raise ValueError(f"`plot_type` must be 'histogram' or 'heatmap', got {plot_type!r}")

    table_paths = _gather_table_paths(inputs)
    if not table_paths:
        raise FileNotFoundError(
            "No tables to summarise. Provide an uploaded file (inputs['<field>_file']), "
            "pipeline upstream artifacts (inputs['upstream'] / inputs['upstream_csvs']), "
            "or inputs['input_dir'] for legacy callers."
        )
    missing = [p for p in table_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Input files not found: {missing}")

    df = pd.concat(
        [_read_table(p, input_format) for p in table_paths], ignore_index=True
    )
    n_rows = len(df)
    numeric_cols = _identify_numeric_columns(df)
    logger.info(
        "Generating %s report: %d row(s), %d numeric column(s), include_plots=%s",
        fmt,
        n_rows,
        len(numeric_cols),
        include_plots,
    )

    plots: list[str] = []
    if include_plots and numeric_cols:
        label_col = _identify_label_column(df) if plot_type == "heatmap" else None
        plots = _render_plots(df, numeric_cols, plot_type=plot_type, label_col=label_col)

    html_content = _render_html(
        title=title,
        n_rows=n_rows,
        numeric_cols=numeric_cols,
        # head(50) keeps the rendered table from ballooning the report for
        # thousand-row inputs.
        table_html=df.head(50).to_html(index=False, classes="results"),
        plot_images=[_data_uri(p) for p in plots],
        include_plots=include_plots,
    )

    if fmt == "html":
        report_filename = "report.html"
        write_artifact(report_filename, html_content)
    else:
        # Plots are inlined as data URIs, so WeasyPrint needs no base_url.
        from weasyprint import HTML

        report_filename = "report.pdf"
        report_path = artifact_path(report_filename)
        HTML(string=html_content).write_pdf(str(report_path))

    logger.info("Wrote %s", report_filename)

    # The runtime persists this dict as /work/output/result.json.
    return {
        "report_file": report_filename,
        "format": fmt,
        "n_rows": n_rows,
        "numeric_columns": numeric_cols,
        "plots": plots,
    }
