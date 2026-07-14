#!/usr/bin/env bash
# Run the autodock-vina tool through its container, exactly as the platform
# worker does — no host install of vina/obabel/rdkit needed.
#
# Usage:
#   ./examples/run-in-docker.sh                              # dock the bundled example
#   ./examples/run-in-docker.sh -l ligands.json -r rec.pdb  # your own inputs
#   ./examples/run-in-docker.sh -p params.json -o results   # custom params / output dir
#
# Options (all optional; defaults point at the bundled examples):
#   -l FILE   ligands: [{smiles,id}] JSON, CSV/TSV, or .smi   (default: examples/input.json)
#   -r FILE   receptor PDB                                     (default: examples/receptor.pdb)
#   -p FILE   params JSON (box center/size, exhaustiveness…)   (default: examples/params.json)
#   -o DIR    output directory for result.json + artifacts     (default: ./advina-out)
#   -i IMAGE  tool image                                       (default: techneos/autodock-vina:latest)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LIGANDS="${SCRIPT_DIR}/input.json"
RECEPTOR="${SCRIPT_DIR}/receptor.pdb"
PARAMS="${SCRIPT_DIR}/params.json"
OUTDIR="$(pwd)/advina-out"
IMAGE="techneos/autodock-vina:latest"

while getopts "l:r:p:o:i:h" opt; do
    case "$opt" in
        l) LIGANDS="$OPTARG" ;;
        r) RECEPTOR="$OPTARG" ;;
        p) PARAMS="$OPTARG" ;;
        o) OUTDIR="$OPTARG" ;;
        i) IMAGE="$OPTARG" ;;
        h) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "run with -h for usage" >&2; exit 2 ;;
    esac
done

for f in "$LIGANDS" "$RECEPTOR" "$PARAMS"; do
    [[ -f "$f" ]] || { echo "error: file not found: $f" >&2; exit 1; }
done

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "error: image '$IMAGE' not found. Build it first:" >&2
    echo "  uv run python packages/tool-runtime/build_and_register.py --skip-register   # builds techneos/tool-runtime" >&2
    echo "  docker build -t techneos/autodock-vina tools/autodock-vina" >&2
    exit 1
fi

# Stage a /work dir in the layout the generic runtime expects: input files +
# inputs.json (resolved paths) + params.json; output/ is collected afterwards.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/input" "$WORK/output"

cp "$LIGANDS" "$WORK/input/ligands.json"
cp "$RECEPTOR" "$WORK/input/receptor.pdb"
cp "$PARAMS" "$WORK/params.json"
cat > "$WORK/inputs.json" <<'JSON'
{"compounds_file": "/work/input/ligands.json", "receptor_file": "/work/input/receptor.pdb"}
JSON

echo "==> Docking ($IMAGE)"
docker run --rm -v "$WORK:/work" "$IMAGE"

mkdir -p "$OUTDIR"
cp -R "$WORK/output/." "$OUTDIR/"

echo
echo "==> Wrote results to $OUTDIR/"
ls -1 "$OUTDIR"
echo
if command -v python3 >/dev/null 2>&1; then
    python3 - "$OUTDIR/result.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
s = d.get("summary", {})
if d.get("error"):
    print("Error:", d["error"]); sys.exit(0)
print(f"Docked {s.get('docked')}/{s.get('total')}  "
      f"best={s.get('best_id')} @ {s.get('best_affinity')} kcal/mol  "
      f"failed={s.get('failed')}")
for r in d.get("results", []):
    print(f"  #{r['rank']:<2} {r['id']:<20} {r['affinity']:>7} kcal/mol  ({r['num_poses']} poses)")
PY
fi
