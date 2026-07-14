# Synthesis Request

Request synthesis of target compounds from the medicinal chemistry team. This
is an offline human task — the request is dispatched as an assignment to a
synthesis chemist or chemistry team.

## Input

- **SDF file** containing target compound structures with compound IDs in SD tags
- **Project name** and request context
- **Desired amounts** and per-compound synthesis notes

## Output

A **Certificate of Analysis (CoA)** for each compound:

| Field | Description |
|---|---|
| Identity | Confirmed by NMR (`1H`, `13C`) and HRMS |
| Purity | HPLC area% or qNMR purity |
| Quantity | Delivered amount and physical form |
| Storage | Recommended storage conditions |
| Batch | Internal batch/lot number |

## Workflow

1. **Assign** — a project lead or automation dispatches the request to a
   synthesis team member.
2. **Synthesize** — the chemist plans and executes the synthesis.
3. **Analyze** — purified compounds are characterized (NMR, MS, HPLC).
4. **Report** — the CoA PDF is generated, signed, and uploaded as an
   attachment.
5. **Complete** — the assignment is marked done; the output data flows
   downstream.

## Examples

See `examples/` for sample input/output:

- `examples/input.sdf` — SDF with 2 compounds (DD-2026-001, DD-2026-002)
  including Compound_ID SD tags, desired amounts, and synthesis notes.
- `examples/output.json` — Corresponding Certificate of Analysis with
  full analytical data (NMR, HPLC, HRMS), batch numbers, and storage
  conditions.

## Pipeline Integration

Use the `synthesis-request` tool slug when building pipelines. The
orchestrator creates a human assignment with the input schema fields
above and waits for the CoA attachments.
