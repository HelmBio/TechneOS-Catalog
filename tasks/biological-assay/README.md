# Biological Assay Request

Request biological assay profiling of hit compounds from the assay biology
team. This is an offline human task — the request is dispatched as an
assignment to an assay biologist or biology team.

## Input

- **Compound list** — compound IDs and SMILES structures to be assayed
- **Assay protocols** — one or more assay protocols selected from the
  predefined list (dose-response, counterscreens, biophysical binding,
  cellular assays, ADME profiling, selectivity panels)
- **Target / cell line context** — the biological target or cell line
  for each protocol
- **Plate format** and **replicates**

## Output

- **Dose-response curves** — IC50/EC50 values, Hill slopes, curve fits
- **Quality metrics** — Z'-factor, signal-to-background, signal-to-noise
- **Per-compound results** — activity flags with quality classification
  (pass / warn / fail)
- **Assay reports** — raw data and any supporting files

## Workflow

1. **Submit** — a project lead or automation dispatches the request to an
   assay biologist, specifying compounds and assay panel.
2. **Plan** — the biologist selects protocols, prepares reagents, and
   designs the plate layout.
3. **Execute** — assays are run (dose-response, counterscreens, binding,
   cellular, ADME, or selectivity as requested).
4. **Analyze** — data is fitted and QC metrics are computed.
5. **Report** — results and dose-response curves are uploaded as
   attachments; the assignment is marked done.

## Examples

See `examples/` for sample input/output:

- `examples/input.csv` — CSV with 5 hit compounds
- `examples/input.json` — Same compounds in JSON format
- `examples/params.json` — Corresponding assay parameters (protocols,
  target, plate format, replicates) that produce the results below
- `examples/output.json` — Simulated assay results with dose-response
  curves, IC50 values, and plate QC metrics.

## Pipeline Integration

Use the `biological-assay` tool slug when building pipelines. The
orchestrator creates a human assignment with the input schema fields
above and waits for the assay results.
