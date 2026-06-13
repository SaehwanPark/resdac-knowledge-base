# CMS Knowledge Base User Manual

Welcome to the CMS Documentation Knowledge Base! This manual is designed for health policy researchers, scientists, analysts, and other users who need to navigate, search, and understand public CMS and ResDAC data structures.

The knowledge base is built to be a reliable, offline-first, citation-backed repository of CMS documentation. It ensures that whenever you ask a question or search for a variable, you get a direct answer backed by the exact source document and URL it came from.

---

## 1. Core Concepts

To make the most of this knowledge base, it is helpful to understand the primary types of records stored in the system:

*   **Datasets**: High-level CMS data products (e.g., Medicare Beneficiary Summary File, Part D Event Data).
*   **Documents**: Documentation pages, user guides, codebooks, spreadsheets, and PDFs linked to datasets.
*   **Variables**: Specific data elements (e.g., `BENE_ID`, `MSIS_ID`, `CLM_ID`) along with their definitions, years of availability, and source references.
*   **Graph Seeds**: Pre-defined relationships linking programs, datasets, documents, and variables together.
*   **Parsed Chunks**: Small, searchable segments of text extracted from raw HTML, PDF, or Excel documents, mapping back to their original page number or source document.
*   **Citations**: The specific URL, local file path, and page number proving where an extracted fact or variable definition was found.

---

## 2. Searching the Knowledge Base

You can search across all datasets, documents, variables, and parsed text chunks using the search interface.

### Running Search Queries

If you have the command-line interface set up, you can perform lexical search queries directly from your terminal.

To search for a variable or topic (for example, `BENE_ID`):

```bash
uv run cms-kb-search --query BENE_ID --limit 5 --json
```

### Understanding Search Results

Search results return structured JSON containing:
1.  `record_id`: A unique identifier for the result.
2.  `record_type`: Whether the hit is a `dataset`, `document`, `variable`, or text `chunk`.
3.  `title`: The name of the record.
4.  `snippet`: A brief excerpt showing where the query matched.
5.  `citation`: The exact source provenance, including:
    *   `source_url`: The public web address where the documentation lives.
    *   `source_document`: The local archived file location.
    *   `page`: The page number (for PDF documents) where the text was found.

#### Example Search Result:

```json
{
  "record_id": "mbsf__bene_id",
  "record_type": "variable",
  "title": "BENE_ID",
  "dataset_id": "mbsf",
  "score": 1.25,
  "snippet": "BENE_ID - Encrypted Master Beneficiary ID. This variable uniquely identifies a beneficiary...",
  "citation": {
    "source_url": "https://resdac.org/cms-data/variables/bene-id",
    "source_document": "data/raw/html/dataset_page/mbsf.html",
    "page": null
  }
}
```

---

## 3. Answering Common Research Questions

Here are some examples of research questions this knowledge base is designed to support, along with how to approach them:

### A. "Which files contain Medicare Advantage encounter information?"
You can search the knowledge base for "encounter" or "Medicare Advantage":

```bash
uv run cms-kb-search --query "encounter" --limit 5
```

This will surface datasets like the *Medicare Advantage Encounter Data* along with their source pages and user guides.

### B. "Where is dual eligibility documented?"
Search for "dual eligibility" to find variables, user guides, or specific text chunks explaining how dual-eligible beneficiaries are represented across Medicare and Medicaid files:

```bash
uv run cms-kb-search --query "dual eligibility" --limit 5
```

This will return variable records like `DUAL_ELG` and documentation chunks detailing the linkage process.

### C. "Where can I find the definition and years for BENE_ID?"
Search for `BENE_ID` using the search tool:

```bash
uv run cms-kb-search --query "BENE_ID" --limit 3
```

The returned metadata will specify which datasets contain `BENE_ID`, its definition, aliases, and years of availability.

---

## 4. AI Agent Integration (MCP Server)

For users utilizing AI assistants (such as Claude Desktop or custom LLM clients), this knowledge base includes a **Model Context Protocol (MCP)** server. 

The MCP server allows your AI agent to interact directly with the local knowledge base, making it a "CMS Research Copilot" that can retrieve documentation and citations without hallucinating.

The AI assistant can invoke the following tools:

*   `search_datasets(query, limit)`: Searches high-level CMS dataset metadata.
*   `search_documents(query, limit)`: Searches attached documentation references.
*   `search_variables(query, limit)`: Searches variable-level metadata (definitions, years, aliases).
*   `search_chunks(query, limit)`: Searches the full text of all parsed HTML, PDF, and Excel documents.
*   `get_agent_context(query, limit)`: Returns a unified, citation-preserving retrieval context hit stream.

### Example Agent Workflow

When you ask your AI assistant: *"What is the definition of MSIS_ID in Medicaid files?"*
The agent will execute:

1.  `search_variables(query="MSIS_ID")` or `get_agent_context(query="MSIS_ID")`
2.  Receive the structured citation:
    *   *Definition*: Medicaid Statistical Information System ID.
    *   *Source Document*: `data/raw/html/documentation_page/taf_dictionary.html`
    *   *Source URL*: `https://resdac.org/cms-data/variables/msis-id`
3.  Formulate a response that cites these details exactly, ensuring correctness.

---

## 5. Trust and Provenance

Every dataset, document, and variable in the knowledge base is verified. 
*   **Checksum Verification**: All archived source files (HTML, PDFs, spreadsheets) are hashed (SHA-256) and recorded in `manifests/archive_manifest.csv`.
*   **No Hallucinations**: Downstream extraction tools are restricted to documented facts. If a provenance trail is missing or ambiguous, the pipeline is designed to skip or raise validation errors rather than guess.
*   **Reproducibility**: You can rebuild the entire metadata and search index locally at any time from the archived raw source files.
