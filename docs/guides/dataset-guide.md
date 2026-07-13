# Dataset Registration Guide

This guide covers the complete lifecycle for registering, versioning, and
discovering datasets on the TechneOS platform. It uses
**ZINC20** as a worked example throughout.

---

## Table of Contents

1. [Dataset Types](#dataset-types)
2. [Registering a Dataset](#registering-a-dataset)
3. [Uploading Versions](#uploading-versions)
4. [Version Lifecycle](#version-lifecycle)
5. [Subscription & Notifications](#subscription--notifications)
6. [Using Datasets in Pipelines](#using-datasets-in-pipelines)
7. [Using Datasets in Agents](#using-datasets-in-agents)
8. [Web Portal Walkthrough](#web-portal-walkthrough)
9. [ZINC20 Example — Full Walkthrough](#zinc20-example--full-walkthrough)
10. [Best Practices](#best-practices)

---

## Dataset Types

TechneOS supports five data types:

| Type         | Description                                          | Example                        |
|--------------|------------------------------------------------------|--------------------------------|
| `molecular`  | Molecular structure data (SMILES, SDF, MOL2)         | ZINC20, ChEMBL exports         |
| `sequence`   | Protein or nucleotide sequences (FASTA, VCF)         | UniProt subsets, gnomAD        |
| `tabular`    | Structured tabular data (CSV, TSV, Parquet)           | Assay results, ADMET data      |
| `image`      | Image data (microscopy, X-ray crystallography)        | Cell Painting, cryo-EM images  |
| `other`      | Any other format                                      | Custom binary formats          |

The `data_type` field is used for filtering and search in the web portal and API.

---

## Registering a Dataset

### Via API

```bash
curl -X POST http://localhost:8000/api/v1/datasets \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ZINC20",
    "slug": "zinc20",
    "description": "A 20,000-molecule sample from the ZINC20 database",
    "data_type": "molecular",
    "tags": ["zinc", "drug-like", "smiles", "benchmark"],
    "data_schema": {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "type": "object",
      "required": ["smiles", "selfies", "zinc_id"],
      "properties": {
        "smiles": {"type": "string"},
        "selfies": {"type": "string"},
        "zinc_id": {"type": "string"}
      }
    },
    "metadata": {
      "source": "https://huggingface.co/datasets/zpn/zinc20",
      "license": "MIT",
      "format": "TSV (smiles, selfies, zinc_id)"
    },
    "is_public": true
  }'
```

### Via Web Portal

Go to **/datasets/new** to register a dataset (metadata only). After
submission, you are redirected to the detail page where you can upload files
as a new version.

### Required Fields

| Field         | Rules                                                                                       |
|---------------|---------------------------------------------------------------------------------------------|
| `name`        | 1-255 characters                                                                            |
| `slug`        | Lowercase alphanumeric + `.`, `-`, `_`. Unique. Must start with alphanumeric.               |
| `data_type`   | One of: `tabular`, `molecular`, `sequence`, `image`, `other`                                |
| `data_schema` | Non-empty JSON Schema describing one record, with `$schema` set to `https://json-schema.org/draft/2020-12/schema`. See [Data Schema](#data-schema) below. |

### Optional Fields

| Field         | Type            | Description                                                                |
|---------------|-----------------|----------------------------------------------------------------------------|
| `description` | string          | Free-text description (supports long text)                                  |
| `file_format` | string          | `csv`, `tsv`, `parquet`, `sdf`, `pdb`, `fasta`, `json`. Used to validate uploads. |
| `tags`        | list of strings | Searchable tags for discoverability                                         |
| `metadata`    | JSON object     | Arbitrary key-value metadata (source, license, citation, etc.)              |
| `is_public`   | boolean         | `false` by default. Public datasets are visible to all users.               |

---

## Uploading Versions

Each dataset has one or more versions. Versions are numbered monotonically
(1, 2, 3, ...) and each can contain one or more files. All files in a batch
upload are grouped under the same version.

- **Files**: One or more data files (uploaded to MinIO object storage)
- **File metadata**: Per-file name, size, content type, SHA-256 checksum (stored in `files` JSONB array)
- **Row/column counts**: Auto-detected where possible
- **Description**: What changed in this version
- **Status**: `uploading` → `ready` (or `failed`)

### Storage Layout

Uploaded files land in the platform's MinIO bucket (`techneos-data`) under a
slug-based prefix:

```
techneos-data/datasets/{slug}/v{N}/{file_name}
```

For example, ``techneos-data/datasets/zinc20/v1/zinc20_druglike.tsv``. The slug
is used (not the UUID) so the bucket is human-browsable; slugs are unique
and immutable, so the layout is stable. The exact storage key for every
file is recorded on the version's `files` array, so downloads and
deletions go through the stored key directly.

Deleting a dataset (``DELETE /api/v1/datasets/{id}``) removes both the DB
rows *and* every backing object in MinIO; the same is true for per-version
deletes. ``register.py --upsert`` relies on this — the old version's files
are cleaned up before the new ones are written.

### Via API

```bash
# Single or multi-file batch upload (single version)
curl -X POST http://localhost:8000/api/v1/datasets/{dataset_id}/versions/batch \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@zinc20_druglike.tsv" \
  -F "files=@zinc20_clean.tsv" \
  -G --data-urlencode "description=20,000-molecule sample with drug-like and clean subsets"
```

### Replace Files in an Existing Version

```bash
# Replaces all files in the specified version
curl -X PUT http://localhost:8000/api/v1/datasets/{dataset_id}/versions/{version_id}/files \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@updated_data.tsv"
```

### Download a Version

```bash
# Via API (returns a presigned MinIO URL)
curl http://localhost:8000/api/v1/datasets/{dataset_id}/versions/{version_id}/download \
  -H "Authorization: Bearer $TOKEN"

# Download a specific file within a multi-file version
curl http://localhost:8000/api/v1/datasets/{dataset_id}/versions/{version_id}/files/{file_index}/download \
  -H "Authorization: Bearer $TOKEN"
```

---

## Version Lifecycle

Dataset versions start as `uploading` and transition to `ready` (or `failed`)
after the upload completes. The platform stores files in MinIO with SHA-256
checksums for integrity verification.

Each version record includes:

| Field             | Description                                    |
|-------------------|------------------------------------------------|
| `version`         | Auto-incrementing integer (1, 2, 3, ...)       |
| `files`           | JSONB array of per-file metadata (name, size, content type, storage key, checksum) |
| `content_type`    | MIME type of the primary file                  |
| `checksum_sha256` | SHA-256 hash of the primary file               |
| `row_count`       | Number of data rows (if detectable)            |
| `column_count`    | Number of columns (if detectable)              |
| `status`          | `uploading` \| `ready` \| `failed`             |
| `description`     | Human-readable description of this version     |

---

## Subscription & Notifications

### Subscribing to a Dataset

Users can subscribe to datasets to receive notifications when new versions
are uploaded.

**Via API:**
```bash
# Subscribe to a specific dataset
curl -X POST http://localhost:8000/api/v1/subscriptions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resource_type": "dataset", "resource_id": "{dataset_id}"}'

# Subscribe to ALL new datasets (category-level)
curl -X POST http://localhost:8000/api/v1/subscriptions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resource_type": "dataset", "resource_id": "*"}'

# Check subscription status
curl "http://localhost:8000/api/v1/subscriptions/check?resource_type=dataset&resource_id={dataset_id}" \
  -H "Authorization: Bearer $TOKEN"

# Unsubscribe
curl -X DELETE http://localhost:8000/api/v1/subscriptions/{subscription_id} \
  -H "Authorization: Bearer $TOKEN"
```

**Via Web Portal:**
Click the **bookmark icon** on any dataset's list row or detail page. The
tooltip shows "Subscribe for notifications" / "Unsubscribe from notifications".

**Category-level subscriptions:**
Go to **Settings > Notification Settings** (accessible from the profile
dropdown) and toggle the **Datasets** switch. This creates a wildcard
subscription (`resource_id="*"`) so you are notified whenever any new
dataset is created.

### Notification Events

Two dataset events trigger notifications:

| Event                       | When                                | Notification message                    |
|-----------------------------|-------------------------------------|-----------------------------------------|
| `dataset.created`           | A new dataset is registered         | "New dataset: {name}"                   |
| `dataset.version.uploaded`  | A new version is uploaded           | "New version {v} of dataset {name}"     |

Notifications are delivered via:
1. **EventBus** (Valkey pub/sub) — primary, real-time
2. **HTTP fallback** — direct POST to notification service if EventBus fails

### Viewing Notifications

- Click the **bell icon** in the top navigation bar
- Notifications show the dataset name and version details
- Click a notification to navigate to the dataset detail page
- Use "Mark all read" to clear the badge

---

## Using Datasets in Pipelines

Pipelines reference datasets by ID in their step configurations:

```json
{
  "steps": [
    {
      "id": "step-1",
      "name": "Load Molecules",
      "tool_slug": "rdkit",
      "parameters": {
        "dataset_id": "{dataset_id}",
        "dataset_version": 1
      }
    }
  ]
}
```

The pipeline engine resolves the dataset version, retrieves the file from
MinIO, and makes it available to the tool execution environment.

---

## Using Datasets in Agents

Agents can search and browse datasets using the **platform tools**:

```
User: "What datasets do we have for virtual screening?"

Agent: [calls search_datasets("virtual screening")]
  → Returns matching datasets with names, descriptions, and metadata

Agent: [calls get_dataset_info("{dataset_id}")]
  → Returns full details including version history and download URLs
```

Platform tools make authenticated API calls using the user's JWT, so RBAC
scoping is respected — users only see datasets they have access to.

---

## Web Portal Walkthrough

### Dataset List Page (`/datasets`)

- **Search**: Type to filter datasets by name or description
- **Columns**: Name, Data Type, Creator, Organization, Public, Created
- **Subscribe**: Bookmark icon on each row for quick subscribe/unsubscribe
- **Click** a dataset name to view its detail page

### Dataset Detail Page (`/datasets/{id}`)

The detail page shows:

1. **Header**: Name, subscribe button, editable metadata (for admins), export metadata JSON
2. **Slug reference**: Dataset slug displayed inline for use in pipelines and agents
3. **Data Schema** *(collapsible)*: Column names, types, and descriptions
4. **Metadata** *(collapsible)*: Key-value metadata with raw JSON export
5. **Summary stats**: Files (size + count), Organization (org + creator)
4. **Version history**: Expandable cards for each version showing:
   - Version number with "latest" badge
   - File size and file count
   - Creator name and date
   - Download all as zip (shown when >1 file and status is `ready`), per-file downloads, replace files button (shown when status is not `ready`)
   - Version description
5. **New Version** button: Opens upload modal to add a new version

---

## Dataset Layout

Each dataset is a self-contained directory under ``datasets/``. A dataset builds
nothing — no wheel, no image — so it has no ``pyproject.toml``; registration is
purely an API call driven by ``register.py`` (the same shape as ``tasks/`` and
``pipelines/``). See [the catalog README](../../README.md) for the overall structure.

```
datasets/
  zinc20/                       # dataset slug as directory name
    dataset_def.json            # full DatasetCreate body — name/slug/tags/
                                # data_schema/file_format/metadata/...
    register.py                 # registers the dataset + uploads version 1
    download_from_huggingface.py  # fetches data from HuggingFace (optional per-dataset)
    data/                       # data files (gitignored — download or copy manually)
      .gitkeep
```

> **Note**: ``dataset_def.json`` is the single source of truth for a dataset.
> It mirrors the ``POST /api/v1/datasets`` body, so every field the API
> understands lives in one file. The required ``data_schema`` field is a
> JSON Schema describing one record (e.g., a CSV row or a JSON object), with its
> ``$schema`` set to ``https://json-schema.org/draft/2020-12/schema``; the API
> rejects creates without a non-empty schema.

Two-step workflow:
1. **Get the data** — download from source or copy a file into ``data/``
2. **Register** — run ``register.py`` which uploads the data as dataset version 1

``register.py`` is constants + a single
`management.catalog.register_dataset` (`packages/management/src/management/catalog.py` in the platform repo)
call — no build step, since a dataset has no wheel/image:
- `start_session` for auth; `resolve_dataset_file(args.file, default_dir)` resolves
  the `.tsv` from `--file` (file or directory) or the `data/` directory
- `register_dataset` checks for an existing dataset by slug (idempotent), creates
  it from `dataset_def.json`, and uploads the file as a version
- `--env local`, `--upsert` (recreate), `--new-version` (add a version to an
  existing dataset)

---

## ZINC20 — Full Walkthrough

End-to-end instructions for registering ZINC20 into your local platform. It
assumes the platform is already running and you have admin credentials —
``register.py`` logs in and caches a token under ``~/.techneos/``.

### About ZINC20

[ZINC20](https://zinc20.docking.org) is a free database of commercially
available compounds for virtual screening, containing over 1 billion
purchasable molecules. The platform includes a 20,000-molecule sample sourced
from the [HuggingFace zpn/zinc20](https://huggingface.co/datasets/zpn/zinc20)
dataset.

The sample contains three columns:
- **smiles** — Canonical SMILES string
- **selfies** — SELFIES representation
- **zinc_id** — ZINC database identifier

### Step 1: Get the Data

Two options — download from HuggingFace or use a local file.

**Option A — Download from HuggingFace:**

```bash
uv run python datasets/zinc20/download_from_huggingface.py
```

Downloads 20,000 molecules and saves them to
``datasets/zinc20/data/zinc20_druglike.tsv``.
Use ``--count`` to change the number or ``--output`` to set a custom path.

**Option B — Use an existing TSV file:**

```bash
mkdir -p datasets/zinc20/data
cp /path/to/your/data.tsv datasets/zinc20/data/
```

The file must contain at least a ``smiles`` column and be tab-separated.

### Step 2: Register the Dataset

```bash
bin/register.sh datasets/zinc20
```

`bin/register.sh` runs the dataset's `register.py` with the right uv invocation,
which will:
1. Look for data in ``data/`` (or wherever ``--file`` points)
2. Check if a dataset with slug ``zinc20`` already exists
3. Create the dataset metadata via ``POST /api/v1/datasets``
4. Upload the TSV file as version 1 via ``POST /api/v1/datasets/{id}/versions``
5. Publish a ``dataset.created`` event

Arguments after the entry are passed straight through to `register.py`:

**Specifying a custom file or directory:**

```bash
bin/register.sh datasets/zinc20 --file /path/to/data.tsv
bin/register.sh datasets/zinc20 --file /path/to/data_dir/
```

**Re-registering or adding a new version:**

```bash
# Delete existing dataset and recreate (idempotent with --upsert)
bin/register.sh datasets/zinc20 --upsert

# Upload as a new version to the existing dataset
bin/register.sh datasets/zinc20 --new-version
```

### Environment Variables

| Variable             | Required | Description                                         |
|----------------------|----------|-----------------------------------------------------|
| ``PLATFORM_API_URL`` | No       | API gateway URL (default: ``http://localhost:8000``); override in ``.env.dev`` |

### Step 3: Verify

```bash
# $TOKEN is a bearer token — reuse the one cached in Step 2, or log in
curl "http://localhost:8000/api/v1/datasets?q=ZINC20" \
  -H "Authorization: Bearer $TOKEN"
```

Open http://localhost:3000/datasets in the web portal to browse the dataset,
view its metadata, and download files.

### Adding a New Dataset

To add a new dataset to the platform, create a new directory under
``datasets/``:

```
datasets/your-dataset-name/
├── dataset_def.json      # full DatasetCreate body (see structure below)
├── register.py           # registration script
├── download_{source}.py  # optional: fetch data from original source
└── data/                 # data files (gitignored)
    └── .gitkeep
```

The ``register.py`` must:
1. Accept ``--file PATH`` for data sources (file or directory)
2. Use ``management.registration`` helpers for auth, env, and headers
3. Load the create body from ``dataset_def.json`` (the API rejects creates
   without a non-empty ``data_schema``)
4. Call the dataset API (``POST /api/v1/datasets`` and ``POST /api/v1/datasets/{id}/versions``)
5. Be idempotent by checking slug uniqueness

### dataset_def.json structure

A complete example. Top-level keys map 1:1 onto the ``DatasetCreate``
request body, so the file IS the create payload (the register script just
splices in a dynamic ``description`` and POSTs it).

```json
{
  "name": "My Dataset",
  "slug": "my-dataset",
  "description": "...",
  "data_type": "tabular",
  "file_format": "tsv",
  "tags": ["chembl", "smiles"],
  "data_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["smiles"],
    "properties": {
      "smiles": { "type": "string", "description": "Canonical SMILES" },
      "score":  { "type": "number" }
    }
  },
  "metadata": {
    "source": "...",
    "license": "..."
  },
  "is_public": true
}
```

The ``data_schema`` field is required and must be a non-empty JSON Schema
object. For tabular formats (CSV/TSV/Parquet) the service uses
``required`` to check that columns exist and ``properties[*].type`` to
spot-check a sample of rows. For JSON records it validates the full
document.

### Verify in Web Portal

1. Open http://localhost:3000/datasets
2. Find "ZINC20" in the list — note the **molecular** data type
3. Click to open the detail page
4. See the metadata section with source, license, and citation
5. See version 1 in the version history with file size and checksum
6. Click the download button to get a presigned URL
7. Click the bell icon — if you have a category subscription for datasets, you should see a notification

---

## Best Practices

### Naming & Slugs

- Use clear, recognizable names (e.g., "ZINC20" not "zinc-data-v2")
- Slugs should be lowercase, hyphenated or underscored (e.g., `zinc20`, `chembl_targets`)
- Slugs are permanent and cannot be edited after creation — choose carefully
- Slugs must start with an alphanumeric character
- Names are also immutable after creation to prevent confusion

### Data Types

| Type        | When to use                                                |
|-------------|------------------------------------------------------------|
| `molecular` | SMILES, SDF, MOL2, or any molecular structure data         |
| `sequence`  | FASTA, VCF, or protein/nucleotide sequence data            |
| `tabular`   | CSV, TSV, Parquet, or structured tabular data              |
| `image`     | Microscopy images, X-ray crystallography, cryo-EM          |
| `other`     | Everything else (binary formats, mixed data)               |

### Data Schema

The `data_schema` field lets you define the column structure of your dataset.
It's an array of objects, each describing one column:

```json
{
  "columns": [
    {"name": "smiles",       "type": "string",  "description": "Canonical SMILES"},
    {"name": "zinc_id",      "type": "string",  "description": "ZINC database ID"},
    {"name": "logp",         "type": "float",   "description": "Octanol-water partition coefficient"},
    {"name": "molecular_weight", "type": "float", "description": "Molecular weight in g/mol"},
    {"name": "active",       "type": "boolean", "description": "Active in primary assay"}
  ]
}
```

Supported column types: `string`, `integer`, `float`, `boolean`, `date`, `json`.

The data schema is displayed on the dataset detail page in the **Data Schema**
section — ordered above Metadata — and can be edited by admins via the edit
modal. The Create Dataset form also includes a Data Schema textarea.

### Metadata

- Always include a `source` URL pointing to the original data source
- Include `license` information for legal clarity
- Add `citation` for academic datasets
- Include `format` to describe the file structure
- Use `organism` for biological datasets

### Versioning

- Upload new versions when data is updated or expanded
- Use the `description` field to document what changed
- Keep file formats consistent across versions when possible
- Previous versions remain downloadable — version history is immutable

### Tags

- Use lowercase, hyphenated tags (e.g., `drug-like`, `virtual-screening`)
- Include the source database name (e.g., `zinc`, `chembl`, `pubchem`)
- Include the data representation (e.g., `smiles`, `selfies`, `sdf`)
- Include the intended use case (e.g., `benchmark`, `training`, `screening`)

### Access Control

- Use `is_public: true` for community/benchmark datasets
- Private datasets are scoped by RBAC: only users in the same org (and team, depending on role) can see them
- Platform admins can see and edit all datasets regardless of visibility settings
- Org admins and project leads within the same org can edit dataset metadata
- Public datasets appear in search results for all authenticated users
