"""Unit tests for dataset_profiler.core.

Strategy:
1. Pure helpers (_coerce_bool, _gather_table_paths, _identify_numeric_columns,
   _read_table, parse).
2. run() happy paths for HTML output, across CSV/TSV/JSON and both execution
   modes (standalone {field}_file and pipeline upstream).
3. run() error paths.
4. Structural snapshot of the returned dict + the rendered HTML.

The PDF path needs WeasyPrint's native libs (libpango/libcairo) that ship in
the container base image, not on dev machines — it's covered end-to-end by
test_container_smoke.py instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest
from dataset_profiler.core import (
    _HEATMAP_ROW_CAP,
    _coerce_bool,
    _gather_table_paths,
    _identify_label_column,
    _identify_numeric_columns,
    _read_table,
    _render_plots,
    parse,
    run,
)

from techneos_tool_runtime.io import WorkDir

# A generic (non-chemistry) tabular dataset: an id column, three numeric
# columns, and a boolean flag.
_ROWS = [
    {"id": "row-1", "score_a": 46.07, "score_b": -0.0, "score_c": 20.23, "passed": True},
    {"id": "row-2", "score_a": 78.11, "score_b": 2.04, "score_c": 0.0, "passed": True},
    {"id": "row-3", "score_a": 180.16, "score_b": 1.31, "score_c": 63.6, "passed": False},
]
_NUMERIC_COLS = ["score_a", "score_b", "score_c"]


@pytest.fixture(autouse=True)
def _isolate_workdir(tmp_path, monkeypatch):
    """Fresh TECHNEOS_WORK_DIR per test so write_artifact() lands under tmp."""
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    return WorkDir(root=tmp_path)


def _make_csv(path: Path) -> None:
    pd.DataFrame(_ROWS).to_csv(path, index=False)


def _make_tsv(path: Path) -> None:
    pd.DataFrame(_ROWS).to_csv(path, sep="\t", index=False)


def _make_json(path: Path) -> None:
    path.write_text(json.dumps(_ROWS))


# ── helpers ────────────────────────────────────────────────────────────


def test_coerce_bool():
    assert _coerce_bool(None, default=True) is True
    assert _coerce_bool(None, default=False) is False
    assert _coerce_bool(True, default=False) is True
    assert _coerce_bool("yes", default=False) is True
    assert _coerce_bool("FALSE", default=True) is False
    assert _coerce_bool("1", default=False) is True
    assert _coerce_bool(0, default=True) is False


def test_parse_is_pass_through():
    """The runtime hook must return the path unchanged so run() reads the raw
    file itself (rather than the default SMILES-list parsing)."""
    assert parse("/work/input/data.csv", {}) == "/work/input/data.csv"
    assert parse("/work/input/data.json", {"input_format": "json"}) == "/work/input/data.json"


# ── _gather_table_paths: both execution modes ─────────────────────────


def test_gather_standalone_field_file(tmp_path):
    """Standalone uploads arrive as inputs['{field}_file']."""
    csv = tmp_path / "data.csv"
    csv.write_text("x\n1\n")
    paths = _gather_table_paths({"dataset_file": str(csv), "dataset_source": {}})
    assert paths == [csv]


def test_gather_pipeline_upstream_dict(tmp_path):
    """Pipeline artifacts arrive as inputs['upstream'] keyed by step, and the
    non-tabular ones (e.g. .png) are filtered out."""
    csv = tmp_path / "a.csv"
    tsv = tmp_path / "b.tsv"
    png = tmp_path / "plot.png"
    for p in (csv, tsv, png):
        p.write_text("x\n1\n")
    inputs = {"upstream": {"step1": [str(csv), str(png)], "step2": [str(tsv)]}}
    paths = _gather_table_paths(inputs)
    assert paths == [csv, tsv]


def test_gather_prefers_field_file_and_dedupes(tmp_path):
    """A path reachable via several sources appears once, in first-seen order."""
    csv_a = tmp_path / "a.csv"
    csv_b = tmp_path / "b.csv"
    for p in (csv_a, csv_b):
        p.write_text("x\n1\n")
    inputs = {
        "dataset_file": str(csv_a),
        "upstream_csvs": [str(csv_a), str(csv_b)],
    }
    paths = _gather_table_paths(inputs)
    assert paths == [csv_a, csv_b]


def test_gather_legacy_flat_lists(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("x\n1\n")
    assert _gather_table_paths({"upstream_csvs": [str(csv)]}) == [csv]
    assert _gather_table_paths({"upstream_tables": [str(csv)]}) == [csv]


def test_gather_falls_back_to_input_dir(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "preds.csv").write_text("x\n1\n")
    (tmp_path / "top.tsv").write_text("x\n1\n")
    (tmp_path / "doc.json").write_text("[]")
    paths = _gather_table_paths({"input_dir": str(tmp_path)})
    assert {p.name for p in paths} == {"preds.csv", "top.tsv", "doc.json"}


def test_gather_returns_empty_when_nothing_specified():
    assert _gather_table_paths({}) == []


# ── _read_table: formats + override ───────────────────────────────────


def test_read_table_auto_detects_by_suffix(tmp_path):
    csv, tsv, js = tmp_path / "a.csv", tmp_path / "a.tsv", tmp_path / "a.json"
    _make_csv(csv)
    _make_tsv(tsv)
    _make_json(js)
    for path in (csv, tsv, js):
        df = _read_table(path)
        assert list(df["id"]) == ["row-1", "row-2", "row-3"]
        assert "score_a" in df.columns


def test_read_table_format_override_wins_over_suffix(tmp_path):
    """A TSV with a misleading .csv extension still parses when forced."""
    weird = tmp_path / "data.csv"
    _make_tsv(weird)
    forced = _read_table(weird, input_format="tsv")
    assert list(forced.columns) == ["id", "score_a", "score_b", "score_c", "passed"]


def test_read_table_rejects_unknown_format(tmp_path):
    p = tmp_path / "a.csv"
    _make_csv(p)
    with pytest.raises(ValueError, match="Unsupported input_format"):
        _read_table(p, input_format="xml")


# ── _identify_numeric_columns ─────────────────────────────────────────


def test_identify_numeric_columns_excludes_identifiers():
    df = pd.DataFrame({"smiles": ["A"], "id": [1], "mw": [10.0], "name": ["x"], "logp": [0.5]})
    assert _identify_numeric_columns(df) == ["mw", "logp"]


def test_identify_numeric_columns_excludes_non_numeric():
    df = pd.DataFrame({"mw": [10.0], "label": ["good"]})
    assert _identify_numeric_columns(df) == ["mw"]


def test_identify_numeric_columns_excludes_booleans():
    """Regression: bool dtypes pass is_numeric_dtype but histogramming them
    breaks on numpy>=2 (boolean subtraction is no longer allowed). They're
    flags, not data columns — exclude them."""
    df = pd.DataFrame(
        {
            "mw": [10.0, 20.0],
            "lipinski_pass": [True, False],
            "valid": pd.array([True, True], dtype="bool"),
        }
    )
    assert _identify_numeric_columns(df) == ["mw"]


def test_run_handles_table_with_boolean_columns(tmp_path):
    """Regression: a real dataset often has bool flag columns that pandas reads
    as bool. Earlier the histogramming code crashed on them."""
    csv = tmp_path / "data.csv"
    _make_csv(csv)  # has a `passed` bool column
    result = run(
        inputs={"upstream_csvs": [str(csv)]},
        params={"format": "html", "include_plots": True},
    )
    assert "passed" not in result["numeric_columns"]
    assert set(result["numeric_columns"]) == set(_NUMERIC_COLS)
    assert set(result["plots"]) == {f"plot_{c}.png" for c in _NUMERIC_COLS}


# ── plots: histogram vs heatmap ───────────────────────────────────────


def test_identify_label_column_picks_first_non_numeric():
    df = pd.DataFrame({"id": ["a"], "score": [1.0], "name": ["x"]})
    assert _identify_label_column(df) == "id"
    # all-numeric -> None (fall back to row index)
    assert _identify_label_column(pd.DataFrame({"a": [1], "b": [2.0]})) is None


def test_render_plots_heatmap_writes_single_image(tmp_path, monkeypatch):
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    (tmp_path / "output").mkdir()
    df = pd.DataFrame(_ROWS)
    plots = _render_plots(df, _NUMERIC_COLS, plot_type="heatmap", label_col="id")
    assert plots == ["heatmap.png"]
    assert (tmp_path / "output" / "heatmap.png").exists()


def test_render_plots_heatmap_falls_back_over_row_cap(tmp_path, monkeypatch):
    """A heatmap can't label thousands of rows, so it falls back to per-column
    histograms beyond the cap."""
    monkeypatch.setenv("TECHNEOS_WORK_DIR", str(tmp_path))
    (tmp_path / "output").mkdir()
    big = pd.DataFrame({"id": [f"r{i}" for i in range(_HEATMAP_ROW_CAP + 10)],
                        "score": list(range(_HEATMAP_ROW_CAP + 10))})
    plots = _render_plots(big, ["score"], plot_type="heatmap", label_col="id")
    assert plots == ["plot_score.png"]
    assert (tmp_path / "output" / "plot_score.png").exists()
    assert not (tmp_path / "output" / "heatmap.png").exists()


def test_run_heatmap_plot_type(tmp_path):
    csv = tmp_path / "data.csv"
    _make_csv(csv)
    result = run(
        inputs={"dataset_file": str(csv)},
        params={"format": "html", "include_plots": True, "plot_type": "heatmap"},
    )
    assert result["plots"] == ["heatmap.png"]
    assert (tmp_path / "output" / "heatmap.png").exists()
    # one combined image, embedded inline (self-contained report)
    html = (tmp_path / "output" / "report.html").read_text()
    assert html.count("<img") == 1
    assert html.count('src="data:image/png;base64,') == 1


def test_run_rejects_bad_plot_type(tmp_path):
    csv = tmp_path / "data.csv"
    _make_csv(csv)
    with pytest.raises(ValueError, match="plot_type.*histogram.*heatmap"):
        run(inputs={"dataset_file": str(csv)}, params={"plot_type": "scatter"})


# ── run() happy paths ─────────────────────────────────────────────────


def test_run_html_format_writes_report(tmp_path):
    csv = tmp_path / "data.csv"
    _make_csv(csv)
    result = run(
        inputs={"dataset_file": str(csv)},
        params={"format": "html", "include_plots": False, "title": "Tiny"},
    )
    assert result["report_file"] == "report.html"
    assert result["format"] == "html"
    assert result["n_rows"] == 3
    assert result["numeric_columns"] == _NUMERIC_COLS
    assert result["plots"] == []

    html = (tmp_path / "output" / "report.html").read_text()
    assert "<title>Tiny</title>" in html
    assert "Total rows: 3" in html
    # include_plots=False => no <img> tags
    assert "<img" not in html

    # The tool does not write its own metadata file — the runtime persists the
    # returned dict as result.json instead.
    assert not (tmp_path / "output" / "report_meta.json").exists()


def test_run_html_with_plots(tmp_path):
    csv = tmp_path / "data.csv"
    _make_csv(csv)
    result = run(
        inputs={"upstream_csvs": [str(csv)]},
        params={"format": "html", "include_plots": True, "title": "Plotted"},
    )
    assert set(result["plots"]) == {f"plot_{c}.png" for c in _NUMERIC_COLS}
    for fname in result["plots"]:
        assert (tmp_path / "output" / fname).exists()
    html = (tmp_path / "output" / "report.html").read_text()
    assert html.count("<img") == 3


def test_run_reads_tsv(tmp_path):
    tsv = tmp_path / "data.tsv"
    _make_tsv(tsv)
    result = run(
        inputs={"dataset_file": str(tsv)},
        params={"format": "html", "include_plots": False},
    )
    assert result["n_rows"] == 3
    assert result["numeric_columns"] == _NUMERIC_COLS


def test_run_reads_json(tmp_path):
    js = tmp_path / "data.json"
    _make_json(js)
    result = run(
        inputs={"dataset_file": str(js)},
        params={"format": "html", "include_plots": False},
    )
    assert result["n_rows"] == 3
    assert result["numeric_columns"] == _NUMERIC_COLS


def test_run_input_format_override(tmp_path):
    """An uploaded TSV with a .csv name still summarises when forced to tsv."""
    weird = tmp_path / "data.csv"
    _make_tsv(weird)
    result = run(
        inputs={"dataset_file": str(weird)},
        params={"format": "html", "include_plots": False, "input_format": "tsv"},
    )
    assert result["n_rows"] == 3
    assert result["numeric_columns"] == _NUMERIC_COLS


def test_run_falls_back_to_input_dir(tmp_path):
    indir = tmp_path / "in"
    indir.mkdir()
    _make_csv(indir / "preds.csv")
    result = run(
        inputs={"input_dir": str(indir)},
        params={"format": "html", "include_plots": False},
    )
    assert result["n_rows"] == 3


def test_run_concatenates_multiple_tables(tmp_path):
    """Pipeline mode: two upstream steps each contribute a table."""
    csv_a = tmp_path / "a.csv"
    tsv_b = tmp_path / "b.tsv"
    _make_csv(csv_a)
    _make_tsv(tsv_b)
    result = run(
        inputs={"upstream": {"step1": [str(csv_a)], "step2": [str(tsv_b)]}},
        params={"format": "html", "include_plots": False},
    )
    assert result["n_rows"] == 6


# ── run() error paths ────────────────────────────────────────────────


def test_run_no_inputs_raises():
    with pytest.raises(FileNotFoundError, match="No tables"):
        run(inputs={}, params={})


def test_run_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="not found"):
        run(
            inputs={"dataset_file": str(tmp_path / "nope.csv")},
            params={"format": "html"},
        )


def test_run_rejects_bad_format(tmp_path):
    csv = tmp_path / "data.csv"
    _make_csv(csv)
    with pytest.raises(ValueError, match="format.*pdf.*html"):
        run(
            inputs={"dataset_file": str(csv)},
            params={"format": "docx"},
        )


# ── structural snapshot ───────────────────────────────────────────────


def test_run_html_structure_snapshot(tmp_path):
    """Lock the returned dict and the rendered scaffolding so downstream
    consumers see a stable result and report structure."""
    csv = tmp_path / "data.csv"
    _make_csv(csv)
    result = run(
        inputs={"dataset_file": str(csv)},
        params={"format": "html", "include_plots": True, "title": "Snapshot"},
    )

    assert result == {
        "report_file": "report.html",
        "format": "html",
        "n_rows": 3,
        "numeric_columns": _NUMERIC_COLS,
        "plots": [f"plot_{c}.png" for c in _NUMERIC_COLS],
    }

    html = (tmp_path / "output" / "report.html").read_text()
    assert "<h1>Snapshot</h1>" in html
    assert "<p>Total rows: 3</p>" in html
    assert "<p>Numeric columns: score_a, score_b, score_c</p>" in html
    # Plots are embedded inline as base64 data URIs (self-contained report),
    # one per numeric column.
    assert html.count("<img") == 3
    assert html.count('src="data:image/png;base64,') == 3
    # id values from the source table survive into the rendered table.
    assert re.search(r"<td>\s*row-1\s*</td>", html)
    assert re.search(r"<td>\s*row-3\s*</td>", html)
