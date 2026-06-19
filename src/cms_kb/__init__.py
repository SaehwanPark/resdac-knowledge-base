"""CMS Knowledge Base core libraries and CLI utilities.

This package exposes the programmatic API components for all pipeline phases:
- Phase 0: Discovery Inventory crawl (`cms_kb.inventory`)
- Phase 1: Archive preservation (`cms_kb.archive`)
- Phase 2: Metadata and ontology extraction (`cms_kb.extraction`)
- Phase 3: Content parsing and text chunking (`cms_kb.parsing`)
- Phase 4: Provenance QA validation (`cms_kb.qa`)
- Phase 6: Variable metadata extraction (`cms_kb.variables`)
- Phase 7: Lexical BM25 search and agent-facing context API (`cms_kb.retrieval`, `cms_kb.agent_api`)
"""

from .agent_api import (
  AgentCitation,
  AgentContextConfig,
  AgentContextHit,
  AgentContextResponse,
  build_agent_context,
)
from .archive import (
  ArchiveConfig,
  ArchiveManifestRow,
  ArchiveResult,
  DownloadResult,
  run_archive,
)
from .extraction import (
  DatasetMetadataRow,
  DocumentEdgeRow,
  DocumentMetadataRow,
  OntologyNodeRow,
  OntologyEdgeRow,
  ExtractionConfig,
  ExtractionFailure,
  ExtractionResult,
  run_extraction,
)
from .inventory import (
  HtmlFetchResult,
  InventoryConfig,
  InventoryResult,
  InventoryRow,
  ProbeResult,
  crawl_inventory,
  main,
  run_inventory,
)
from .parsing import (
  ChunkMetadata,
  ParsingConfig,
  ParsingFailure,
  ParsingResult,
  run_parsing,
)
from .qa import (
  QAConfig,
  QAFinding,
  QAResult,
  run_qa,
)
from .variables import (
  VariableEdgeRow,
  VariableExtractionConfig,
  VariableExtractionFailure,
  VariableExtractionResult,
  VariableMetadataRow,
  run_variable_extraction,
)

__all__ = [
  "AgentCitation",
  "AgentContextConfig",
  "AgentContextHit",
  "AgentContextResponse",
  "ArchiveConfig",
  "ArchiveManifestRow",
  "ArchiveResult",
  "ChunkMetadata",
  "DatasetMetadataRow",
  "DocumentEdgeRow",
  "DocumentMetadataRow",
  "OntologyNodeRow",
  "OntologyEdgeRow",
  "DownloadResult",
  "ExtractionConfig",
  "ExtractionFailure",
  "ExtractionResult",
  "HtmlFetchResult",
  "InventoryConfig",
  "InventoryResult",
  "InventoryRow",
  "ParsingConfig",
  "ParsingFailure",
  "ParsingResult",
  "ProbeResult",
  "QAConfig",
  "QAFinding",
  "QAResult",
  "VariableEdgeRow",
  "VariableExtractionConfig",
  "VariableExtractionFailure",
  "VariableExtractionResult",
  "VariableMetadataRow",
  "build_agent_context",
  "crawl_inventory",
  "main",
  "run_archive",
  "run_extraction",
  "run_inventory",
  "run_parsing",
  "run_qa",
  "run_variable_extraction",
]
