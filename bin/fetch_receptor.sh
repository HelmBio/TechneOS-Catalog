#!/usr/bin/env bash
# Fetch a receptor structure from the RCSB PDB for the hit-triage docking step.
#
# A protein structure can't be hand-authored, so we pull a real one from RCSB.
# autodock-vina preps whatever you give it (strips waters, adds hydrogens +
# Gasteiger charges, converts to PDBQT).
#
# Saves to pipelines/hit-triage/examples/{PDB_ID}_{TARGET}.pdb
#
# Usage:
#   ./bin/fetch_receptor.sh                      # 5VAI / GLP-1R (default)
#   ./bin/fetch_receptor.sh 6X18 GLP-1R          # small-molecule-pocket GLP-1R
#   ./bin/fetch_receptor.sh 3IOL GLP-1R          # GLP-1R extracellular domain
#
# Suggested GLP-1R structures:
#   5VAI  full-length active GLP-1R-Gs complex (7TM domain; peptide-bound)
#   6X18  GLP-1R bound to a small-molecule agonist (7TM small-molecule pocket)
#   3IOL  GLP-1R extracellular domain only (small; not the 7TM pocket)
#
# For docking *small molecules* you want the 7TM pocket, so a full-length
# structure (5VAI / 6X18) is the right choice — the ECD-only 3IOL is handy for
# a fast smoke test but isn't where small molecules bind.

set -euo pipefail

PDB_ID="${1:-5VAI}"
TARGET="${2:-GLP-1R}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXAMPLES_DIR="${REPO_ROOT}/pipelines/hit-triage/examples"
OUT="${EXAMPLES_DIR}/${PDB_ID}_${TARGET}.pdb"
URL="https://files.rcsb.org/download/${PDB_ID}.pdb"

mkdir -p "$EXAMPLES_DIR"
echo "Downloading ${PDB_ID} from RCSB -> ${OUT}"
curl -fsSL "$URL" -o "$OUT"
echo "Saved $(basename "$OUT") ($(wc -l < "$OUT" | tr -d ' ') lines)."

cat <<'NOTE'

Next:
  - In the hit-triage run wizard, upload examples/compounds.json on the
    "screen_alerts" stop and this .pdb on the "dock_vina" stop.
  - To focus docking on the binding pocket, set the dock_vina search box:
    either dock_vina.search_box.center_{x,y,z} to the pocket centre, or
    box_from_ref=true with the co-crystallised ligand. Otherwise vina uses a
    default box centred on the receptor centroid (fine for a smoke test, but a
    whole-receptor box on a 7TM target is not biologically meaningful).
NOTE
