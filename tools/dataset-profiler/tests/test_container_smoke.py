"""Container smoke test — the real PDF path, end to end.

PDF rendering depends on WeasyPrint's native libs (libpango/libcairo), which
this tool's Dockerfile installs on top of the shared `techneos/tool-runtime` base.
So we exercise it where it actually runs: build the tool image and invoke it via
the generic runtime entrypoint, exactly as the worker does, then assert a real
`%PDF` artifact comes back.

The test skips cleanly when Docker or the base image is unavailable (e.g. a CI
job that hasn't built techneos/tool-runtime), so a plain `pytest` run on a dev
machine without Docker stays green.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TOOL_DIR = Path(__file__).resolve().parent.parent
BASE_IMAGE = "techneos/tool-runtime:latest"
SMOKE_TAG = "techneos/dataset-profiler:pytest-smoke"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def _base_image_present() -> bool:
    return (
        subprocess.run(
            ["docker", "image", "inspect", BASE_IMAGE], capture_output=True
        ).returncode
        == 0
    )


pytestmark = [
    pytest.mark.skipif(not _docker_available(), reason="Docker not available"),
    pytest.mark.skipif(
        _docker_available() and not _base_image_present(),
        reason=f"{BASE_IMAGE} missing — run packages/tool-runtime/build_and_register.py --skip-register",
    ),
]


@pytest.fixture(scope="module")
def smoke_image() -> str:
    """Build the tool image once for the module."""
    result = subprocess.run(
        ["docker", "build", "-t", SMOKE_TAG, str(TOOL_DIR)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"docker build failed:\n{result.stderr}")
    return SMOKE_TAG


def test_container_renders_pdf(smoke_image, tmp_path):
    """A CSV in, a real PDF out, via the generic runtime entrypoint."""
    work = tmp_path / "work"
    (work / "input").mkdir(parents=True)
    (work / "output").mkdir(parents=True)
    (work / "input" / "data.csv").write_text(
        "id,score_a,score_b,passed\n"
        "row-1,46.07,-0.0,True\n"
        "row-2,78.11,2.04,True\n"
        "row-3,180.16,1.31,False\n"
    )
    (work / "inputs.json").write_text(
        json.dumps({"dataset_file": "/work/input/data.csv"})
    )
    (work / "params.json").write_text(
        json.dumps({"format": "pdf", "include_plots": True, "title": "Smoke"})
    )

    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{work}:/work", smoke_image],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"container run failed:\n{result.stderr}"

    meta = json.loads((work / "output" / "result.json").read_text())
    assert meta["report_file"] == "report.pdf"
    assert meta["n_rows"] == 3
    assert meta["numeric_columns"] == ["score_a", "score_b"]  # bool `passed` excluded

    pdf = work / "output" / "report.pdf"
    assert pdf.exists()
    assert pdf.read_bytes().startswith(b"%PDF")
