# Legal RAG Studio — Architecture Overview

This document summarizes the architecture of the Legal RAG Studio desktop suite. The goal is to let non-technical analysts ingest, search, and test legal corpora with only a few guided clicks.

## High-level layout

```
PySide6 GUI  ──signals──▶  Async task layer ──HTTP──▶ FastAPI backend ──▶ Qdrant / Storage
            ◀─events────      (QThreadPool)        ◀─WebSocket──
```

* **GUI** – A PySide6 application with five guided workspaces:
  1. **Create Base** – upload documents, choose enrichment options, launch indexing.
  2. **Search & Verify** – semantic search, GPT explanations, relevance metadata.
  3. **Quality Lab** – automated regression checks, coverage metrics, PDF export.
  4. **Settings** – API keys, Qdrant endpoints, theme, connectivity test.
  5. **GPT Assistant** – context aware chat for analysis, drafting, or clarifications.

* **Backend** – A FastAPI service (runs alongside the GUI) which hosts ingestion,
  enrichment, testing, and chat flows. The GUI talks to it through HTTP or
  WebSockets, so long-running tasks do not block the interface.

* **Vector Store** – Qdrant named-vector collections (`title_vec`, `body_vec`) with
  payload metadata (code, article, status, timestamps, etc.).

## Modules

| Path | Purpose |
| ---- | ------- |
| `main.py` | GUI entry-point, sets up navigation, theming, and logging console. |
| `ui/tabs/` | Each tab is implemented as a dedicated widget with helper text. |
| `backend/ingest.py` | File parsing, chunking, enrichment orchestration. |
| `backend/search.py` | Search endpoint plus lexical fallbacks. |
| `backend/enrich.py` | GPT-5-nano helpers for summary/keywords/tooltips. |
| `backend/test_suite.py` | Automated evaluations, PDF/HTML reporting. |
| `backend/ai_client.py` | Shared OpenAI/GPT client with rate limiting + caching. |
| `db/qdrant_client.py` | Connection helper and deterministic id utilities. |
| `utils/parser_rtf.py` | Normalized parsing for TXT/RTF/PDF/DOCX. |
| `utils/chunker.py` | Article/paragraph chunking logic. |
| `utils/logger.py` | Configures rotating file logger + GUI bridge. |
| `utils/config.py` | Persistent config (YAML) for keys, endpoints, theme. |
| `tests/` | Pytest-based sanity checks for parsing, chunking, search mocks. |

## Data flow

1. User selects documents in the **Create Base** tab.
2. GUI posts `/ingest/start` with chosen settings.
3. Backend parses documents, generates metadata, calls GPT-5-nano for concise summaries.
4. Embeddings are produced via `text-embedding-3-large` (cached). Upsert occurs
   against Qdrant with deterministic UUIDs per article/chunk.
5. After ingest, backend triggers a light QA using GPT-4.1 on sampled chunks.
6. GUI receives progress events over WebSocket and updates progress bars/log.

## Quality pipeline

* `tests/test_ingest.py` – verifies chunk counts and metadata integrity using sample fixtures.
* `tests/test_search.py` – runs semantic search on the canned dataset.
* `tests/test_rag.py` – simulates GPT QA scoring via stubbed clients.
* GUI Quality Lab exposes a "Run regression" button; results appear as cards with
  pass/fail badges and can be exported as HTML/PDF.

## Extensibility hints

* Add new parser under `utils/parser_*.py` and register in `backend/ingest.py`.
* For alternative vector stores, replace `db/qdrant_client.py`.
* Add more GPT routines by extending `backend/ai_client.OpenAIManager`.

