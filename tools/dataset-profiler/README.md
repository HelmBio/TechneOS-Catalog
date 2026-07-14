# dataset-profiler

A self-contained **container** tool that profiles any **tabular dataset**
(CSV, TSV, or JSON) into an HTML or PDF report: it concatenates the inputs,
finds the numeric (non-boolean) columns, renders per-column distribution
histograms (or a sample × metric heatmap), and emits a Jinja-templated report
— PDF via WeasyPrint.

It's domain-agnostic (any table works, not just chemistry) and runs in two
modes with no caller changes:

- **Standalone** — a user uploads/pastes/selects one data file.
- **Pipeline** — a step consumes the table artifacts of its upstream steps.

This tool also serves as the **reference example** for the container tool
lifecycle: build → run locally → register → run on the platform.
`tools/molecule-property-calculator` is the counterpart reference for the pypi
lifecycle.

## Layout

```
dataset-profiler/
├── tool_def.json        # single source of truth: metadata + schemas + resources
├── pyproject.toml       # package + [tool.techneos] container coordinates
├── Dockerfile           # builds on techneos/tool-runtime
├── build_and_register.py# build + push + register + activate
├── README.md            # this file (registered as the tool's readme)
├── src/dataset_profiler/
│   ├── core.py          # run(inputs, params) -> dict  (+ parse() hook)
│   └── __init__.py
├── tests/               # unit tests + a container smoke test
└── examples/            # input.csv / input.tsv / input.json + params + result
```

`tool_def.json` is the single source of truth — `build_and_register.py` reads
metadata, the three schemas, and `resource_requirements` from it; the Docker
image name comes from `[tool.techneos]` in `pyproject.toml`.

## Contract

```python
from dataset_profiler import run

result = run(
    {"dataset_file": "/work/input/data.csv"},      # standalone, or...
    {"format": "pdf", "title": "Sample QC Summary"},
)
# result -> {"report_file": "report.pdf", "format": "pdf", "n_rows": 6,
#            "numeric_columns": ["temperature", ...], "plots": ["plot_temperature.png", ...]}
```

The runtime (`techneos_tool_runtime.runner`) parses every `{field}_file` input before
calling `run()`, defaulting to the SMILES-list parser. That's wrong for a
generic table, so `core.py` exports a tiny pass-through `parse()` next to `run`
that returns the path unchanged — `run()` then reads the file itself in whatever
tabular format it is.

### Inputs

| Field                        | Mode       | Notes |
|------------------------------|------------|-------|
| `inputs.{field}_file`        | standalone | An uploaded/pasted/selected file, e.g. `dataset_file`. The worker resolves the path; any `_file` key is treated as a table. |
| `inputs.upstream`            | pipeline   | `{step_name: [paths]}` from the step's `depends_on`. Non-tabular artifacts are ignored. |
| `inputs.upstream_csvs`       | pipeline   | Convenience flat list of the CSV/TSV subset. |
| `inputs.input_dir`           | legacy     | Directory scanned recursively for `*.csv` / `*.tsv` / `*.json`. |

### Parameters

| Param            | Default               | Notes |
|------------------|-----------------------|-------|
| `format`         | `"pdf"`               | `"pdf"` or `"html"`. |
| `include_plots`  | `true`                | Render per-column plots. |
| `title`          | `"Data Summary Report"` | Cover-page title. |
| `input_format`   | `"auto"`              | `auto` infers per file from the extension; force `csv` / `tsv` / `json`. |
| `plot_type`      | `"histogram"`         | `histogram` = per-column distribution; `heatmap` = a single rows=samples × cols=numeric heatmap labelled by the first non-numeric column (e.g. an id), auto-falling back to histograms above 50 rows. |

Side-effect artifacts (`report.{pdf,html}`, `plot_*.png` or `heatmap.png`) are
written under `/work/output/` via the `techneos-tool-runtime` helpers. The returned
dict above is persisted by the runtime as `result.json`.

## Develop and test

```bash
cd tools/dataset-profiler
uv sync                                   # local venv (pandas/matplotlib/jinja2/weasyprint)
uv run --group dev python -m pytest       # unit tests + container smoke test
```

The PDF path needs WeasyPrint's native libs (libpango/libcairo) that ship in
the container base, not on dev machines — it's covered by the container smoke
test (`tests/test_container_smoke.py`), which skips cleanly when Docker or the
base image is unavailable.

## Build the image

The image builds on `techneos/tool-runtime` (Python + `techneos-tool-runtime` + the
runner) and installs WeasyPrint's system libs in its own Dockerfile.

```bash
uv run python packages/tool-runtime/build_and_register.py --skip-register   # build the shared runtime image (once)
docker build -t techneos/dataset-profiler:latest tools/dataset-profiler/
```

## Run locally in the container

The worker bind-mounts a `/work` directory holding `inputs.json` + `params.json`
and an `input/` tree. Reproduce either mode against the shipped examples.

**Standalone** (an uploaded file, JSON in this example):

```bash
cd tools/dataset-profiler
WORK=$(mktemp -d); mkdir -p "$WORK/input" "$WORK/output"
cp examples/input.json "$WORK/input/data.json"
echo '{"dataset_file":"/work/input/data.json"}' > "$WORK/inputs.json"
echo '{"format":"html","input_format":"json","title":"Sample QC Summary"}' > "$WORK/params.json"
docker run --rm -v "$WORK:/work" techneos/dataset-profiler:latest
cat "$WORK/output/result.json"            # n_rows / numeric_columns / plots
```

**Pipeline** (upstream artifacts, CSV → PDF, heatmap):

```bash
WORK=$(mktemp -d); mkdir -p "$WORK/input/upstream/measure" "$WORK/output"
cp examples/input.csv "$WORK/input/upstream/measure/data.csv"
echo '{"upstream_csvs":["/work/input/upstream/measure/data.csv"]}' > "$WORK/inputs.json"
echo '{"format":"pdf","plot_type":"heatmap","title":"Sample QC Summary"}' > "$WORK/params.json"
docker run --rm -v "$WORK:/work" techneos/dataset-profiler:latest
ls "$WORK/output"                         # report.pdf, heatmap.png, result.json
```

`examples/expected_result.json` is the `run()` output for `examples/input.csv`
with `examples/params.json` (HTML).

## Register, publish, and deploy

`build_and_register.py` builds + pushes the image, then registers a new tool
version pointing at the image tag and activates it.

```bash
# Local: builds the image and registers against the local API. Push is skipped
# automatically — the worker shares the local Docker daemon.
bin/register.sh tools/dataset-profiler --env=local --upsert

# Skip the rebuild if the image is already built locally:
bin/register.sh tools/dataset-profiler --upsert --skip-build

```

A static pre-flight checks the Dockerfile's `ENTRYPOINT_SPEC` resolves to a real
function before building; pass `--skip-validation` to bypass it.

## Run on the platform

Once activated, open the tool in the portal
(`http://localhost:3000/tools/<tool_id>`), upload `examples/input.csv`, set the
parameters, and submit a run — the report lands as an output artifact. In a
pipeline, add a `dataset-profiler` step with `depends_on` pointing at the steps
whose tables you want profiled.
