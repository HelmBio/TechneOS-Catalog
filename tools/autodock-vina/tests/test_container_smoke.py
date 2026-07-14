"""Container smoke test — the real docking path, end to end.

Docking depends on the native `vina` and `obabel` binaries and RDKit/Meeko —
all installed into the tool image (apt + pip) on top of the shared
`techneos/tool-runtime` base, none of which are in the plain Python env. So we
exercise it where it actually runs: build the tool image and invoke it via the
generic runtime entrypoint, exactly as the worker does, then assert a real
ranked result comes back.

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
SMOKE_TAG = "techneos/autodock-vina:pytest-smoke"


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


def test_container_docks_and_ranks(smoke_image, tmp_path):
    """Two ligands + a receptor in, a ranked affinity result out."""
    work = tmp_path / "work"
    (work / "input").mkdir(parents=True)
    (work / "output").mkdir(parents=True)

    shutil.copy(TOOL_DIR / "examples" / "receptor.pdb", work / "input" / "receptor.pdb")
    (work / "input" / "ligands.json").write_text(
        json.dumps(
            [
                {"smiles": "CC(=O)Oc1ccccc1C(=O)O", "id": "aspirin"},
                {"smiles": "OC(=O)c1ccccc1O", "id": "salicylic-acid"},
            ]
        )
    )
    (work / "inputs.json").write_text(
        json.dumps(
            {
                "compounds_file": "/work/input/ligands.json",
                "receptor_file": "/work/input/receptor.pdb",
            }
        )
    )
    (work / "params.json").write_text(
        json.dumps(
            {
                "search_box": {
                    "center_x": 10.6, "center_y": 10.2, "center_z": 6.1,
                    "size_x": 22, "size_y": 22, "size_z": 22,
                },
                "exhaustiveness": 1, "num_modes": 3, "seed": 1,
            }
        )
    )

    result = subprocess.run(
        ["docker", "run", "--rm", "-v", f"{work}:/work", smoke_image],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"container run failed:\n{result.stderr}"

    meta = json.loads((work / "output" / "result.json").read_text())
    assert meta["summary"]["docked"] == 2, meta
    assert meta["count"] == 2
    # Affinities are negative kcal/mol and ranked strongest (most negative) first.
    affinities = [r["affinity"] for r in meta["results"]]
    assert all(a < 0 for a in affinities)
    assert affinities == sorted(affinities)
    assert meta["ranking"][0] == meta["results"][0]["id"]
    assert meta["summary"]["best_affinity"] == affinities[0]
