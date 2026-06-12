# ROADMAP

This roadmap records the strategic layering for the project. Use `SPEC.md` as
the operational source of truth for whether a feature is Past, Present, or
Future; these roadmap phases may include completed work and future direction.

Build layers in this order:

```text
Archive
  ↓
Structured Metadata
  ↓
Knowledge Graph
  ↓
Retrieval API
  ↓
Agent Integration
```

That way every layer remains independently useful.

# Phase 0 — Discovery & Scoping (1–2 days)

Goal: understand the ResDAC information architecture before writing much code.

Deliverables:

```text
site_inventory.csv

url
title
content_type
linked_documents
```

Tasks:

* Crawl all `/cms-data?page=k`
* Enumerate every `/cms-data/files/*`
* Enumerate all documentation links
* Enumerate PDFs/XLSX/ZIP assets
* Count unique file pages

Questions to answer:

```text
How many CMS data products?
How many PDFs?
How many variable-level documents?
How many dead links?
```

Output:

```text
inventory.parquet
inventory.csv
```

This inventory itself will be valuable if the site disappears.

---

# Phase 1 — Preservation Archive (1 week)

Goal: create a reproducible local mirror.

Directory:

```text
archive/

  html/
  pdf/
  xlsx/
  csv/

  manifests/
    files.parquet
    downloads.parquet
```

Each file gets:

```json
{
  "url": "...",
  "downloaded_at": "...",
  "sha256": "...",
  "content_type": "...",
  "local_path": "..."
}
```

Store:

* raw HTML
* PDFs
* spreadsheets
* images

Avoid parsing yet.

Success criteria:

```text
100% of publicly available documentation recoverable offline
```

---

# Phase 2 — Metadata Extraction (1–2 weeks)

This is where value begins.

Extract entities from every file page.

Example:

```json
{
  "dataset_name": "Medicare Beneficiary Summary File",
  "program": "Medicare",
  "category": "Enrollment",
  "availability": "...",
  "special_considerations": "...",
  "source_url": "..."
}
```

Store in:

```text
datasets.parquet
```

DuckDB works perfectly here.

Schema:

```sql
datasets
documents
links
downloads
```

At this stage you already have a searchable CMS catalog.

---

# Phase 3 — Document Parsing (2 weeks)

Convert PDFs and HTML into clean text.

Recommended:

```python
trafilatura
pymupdf
unstructured
```

Generate:

```text
parsed/

  html/
  pdf/

  chunks/
```

Each chunk should retain provenance:

```json
{
  "chunk_id": "...",
  "source_document": "...",
  "page": 14,
  "text": "...",
  "dataset": "...",
  "url": "..."
}
```

Provenance is critical for agent trustworthiness.

---

# Phase 4 — CMS Research Ontology (high ROI)

This is the part most RAG projects skip.

Create explicit entities:

```text
Dataset
Table
Variable
Program
Beneficiary
Claim
Encounter
Provider
Drug
Enrollment
```

Relationships:

```text
Dataset -> contains -> Variable

Dataset -> related_to -> Dataset

Variable -> appears_in -> Dataset

Dataset -> belongs_to -> Program
```

Store in:

```text
graph/
```

Even a simple edge list is enough initially.

Example:

```csv
source,target,relationship

MBSF,BENE_ID,contains
PDE,BENE_ID,contains
TAF,Medicaid,belongs_to
```

---

# Phase 5 — Variable-Level Knowledge (largest effort)

This is where the system becomes genuinely useful.

Many CMS questions are actually:

```text
Where is race?
Where is dual eligibility?
Where is MA enrollment?
Where is diagnosis?
```

not

```text
What dataset exists?
```

Create canonical variable records:

```json
{
  "variable": "BENE_ID",
  "definition": "...",
  "datasets": [...],
  "aliases": [...],
  "years": [...]
}
```

Think of this as a CMS data dictionary.

This may require parsing PDFs beyond ResDAC itself.

Potential future sources:

* CMS data dictionaries
* CCW documentation
* VRDC documentation
* TAF technical specifications

---

# Phase 7 — Hybrid Retrieval Layer

Now build retrieval.

I would use:

```text
DuckDB
+
BM25
+
Embeddings
```

not a vector DB initially.

Architecture:

```text
Question

  ↓

Metadata search

  ↓

BM25

  ↓

Embedding rerank

  ↓

Citations
```

For CMS documentation, exact matching often beats embeddings.

Example:

```text
BENE_ID
MSIS_ID
CLM_ID
PDE_ID
```

BM25 excels here.

---

# Phase 8 — Agent Integration

Expose a small toolkit. The repository already has a minimal JSON/Pydantic
agent context CLI; the next integration target is MCP tooling over the same
citation-preserving retrieval surface.

Examples:

```python
search_datasets()

search_variables()

get_dataset()

get_variable()

related_datasets()

citations()
```

MCP should expose read-only tools around existing retrieval and context
functions first, before adding higher-level workflow helpers.

Then an agent can do:

```python
search_variables("dual eligibility")
```

instead of semantic-searching thousands of chunks.

This dramatically reduces hallucinations.

---

# Phase 9 — Evaluation Suite

This is the part I'd insist on if Penn intends real usage.

Create 50–100 benchmark questions from actual projects.

Examples:

```text
Which files identify dual eligibles?

How do I link Part D events to beneficiaries?

What files contain MA encounter diagnoses?

What are known limitations of TAF OT data?
```

Gold-standard answers:

```text
dataset
variable
citation
```

Track:

```text
Recall@5
MRR
citation accuracy
```

---

# Stretch Goal: CMS Research Copilot

Once the KB is stable, you can support workflows like:

```text
Researcher:
  I need beneficiaries with CHF
  between 2016 and 2021.

Agent:
  Use MBSF for enrollment,
  MedPAR for inpatient diagnoses,
  Carrier for physician claims,
  and ICD-10 codes ...
```

with every recommendation grounded in archived documentation.

---

If I were staffing this internally, I'd target:

**Month 1**

* Phases 0–3 complete
* Full ResDAC preservation
* Searchable metadata catalog

**Month 2**

* Ontology + retrieval layer
* Initial agent API

**Month 3+**

* Variable-level knowledge graph
* Evaluation framework
* Research copilot capabilities

The biggest strategic asset is not the archive itself; it's the **variable-level ontology of CMS data assets**. That's the layer current LLMs are weakest at and where your team could build something uniquely valuable.
