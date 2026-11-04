# RAG implementation overview

RAG in this project has two halves. **Ingestion** (`app/pipeline/`) turns files into chunks and vectors that are stored in MongoDB. **Retrieval** (`app/retrieval/` plus `RetrievalAgent`) runs BM25 and vector search together, merges the results with RRF, and reranks them. `app/storage/` is the persistence layer under both. Everything is written by hand; no LangChain or LlamaIndex is used.

## 1. Ingestion: `Indexer.ingest()` in `pipeline/indexer.py`

```
file → dedup check → parse → clean → chunk → (LLM metadata) → embed → write vectors + BM25 + Mongo chunks → archive old version
```

| Step | Module | What it does |
|---|---|---|
| Dedup | `indexer.py` | Hashes the file with SHA-256. Uploading the same file twice to the same department raises `DuplicateDocumentError`. |
| Parse | `parser.py` | Reads PDF (pdfplumber, falling back to pypdf), DOCX (paragraphs and tables in order), Markdown, HTML and TXT. Output is a list of `Block`s (heading / paragraph / list_item / table), each with a level and page number. For TXT and PDF, headings are detected with a regex for Chinese headings such as `第X章` and `一、`. |
| Clean | `cleaner.py` | Converts full-width characters to half-width and collapses whitespace. Drops page-number lines, `第N页共M页` and watermark lines (内部资料 and similar). Converts traditional to simplified Chinese only if `opencc` is installed. |
| Chunk | `chunker.py` | Splits on clause boundaries rather than token counts. A heading stack groups blocks into sections, which gives each chunk a `section_path`. Text is split at clause markers (`第X条`, `（1）`, `1.`) and packed into chunks of 300–600 characters. Pieces that are still too long are cut at sentence punctuation, and short chunks are merged into the previous one. The aim is that every answer can be traced to a specific clause. |
| Metadata | `metadata_extractor.py` | Makes one LLM call in JSON mode on the first 6,000 characters to get `effective_date`, `doc_type`, `keywords`, `applicable_scope` and `cross_refs`. If the call fails, defaults are used. Each chunk also gets jieba TF-IDF keywords, computed locally. |
| Embed | `llm/embeddings.py` | Uses bge-m3 by default. Can also use Ollama, or a hash fallback. |
| Index | `indexer.py` | Writes each chunk `"{doc_id}:{i}"` to three places: the vector store (with `doc_id`, `dept_id` and `chunk_index`), the BM25 index, and the Mongo `chunks` collection (full text, section path, keywords, page, has_table). |

### Versioning and rollback

When a document is uploaded with the same title in the same department, it becomes a new version (`1.1`, `1.2`, …) and its `supersedes` field points to the previous version. The old version is archived and removed from the runtime indexes only after the new version is fully ready. If ingestion fails partway, the vectors, BM25 entries, chunks and document record are all rolled back.

### Conflict detection: `conflict_detector.py`

This runs after ingestion, from `scripts/async_worker.py` and `scripts/ingest_department_files.py`.

- **Rule layer:** a regex finds references such as `根据《XX办法》` and links them to other documents by title (`reference`).
- **Semantic layer:**
  1. For each chunk, vector search finds similar chunks from *other* departments.
  2. Candidates are filtered by score ≥ 0.5 and keyword overlap ≥ 0.15.
  3. The LLM is asked whether the two clauses contradict each other (`conflict`, kept if confidence ≥ 0.6).

Results are written to `doc_relations`.

## 2. Storage: `app/storage/`

- **`store.py`:** `DataStore` is an abstract interface. It provides generic CRUD on dicts (`upsert`, `get`, `find`, `delete`, `count`, `increment`) and domain helpers such as `list_active_chunks`, `insert_relation` and `list_documents`. Two implementations:
  - `MongoStore` (motor), used when `STORAGE_MODE=mongo`.
  - `MemoryStore` (deep-copied dicts), used for tests and offline work.

  There are about 30 collections; the ones RAG uses are `documents`, `chunks`, `vector_embeddings` and `doc_relations`.
- **`mongodb.py`:** connects to MongoDB and creates indexes, for example `chunks(doc_id)`, `documents(dept_id, status)`, `documents(dept_id, source.file_hash)`, and TTL indexes on the memory collections.
- **`redis_store.py`:** holds session working memory (30-minute TTL) and the FAQ cache (1-hour TTL). Falls back to in-memory storage when not in mongo mode.
- **`job_queue.py`:** the async ingestion job queue. Uses Redis Streams with consumer groups, and keeps job status in Mongo `async_jobs`.
- **`models.py`:** Pydantic schemas that document the shapes of `Document`, `Chunk`, `DocRelation`, `Trace` and others. The store itself works with plain dicts.

### Vector and BM25 backends (`VECTOR_BACKEND`)

| Backend | Vectors | BM25 | Notes |
|---|---|---|---|
| `memory` (local default) | Python dict, cosine similarity | in-process `BM25Index` | At startup, `main.py` re-embeds every active chunk to rebuild both indexes. |
| `mongo` (k8s default) | `MongoVectorStore` in `vector_embeddings` | `SharedBM25Index` | Shared across pods; nothing is re-embedded at startup. |
| `chroma` | Chroma, persisted to `./chroma_data` | in-process | Falls back to memory if Chroma fails to initialise. |

## 3. Retrieval at query time

`RetrievalAgent.retrieve()` in `harness/agents/retrieval_agent.py`:

1. Takes the rewritten queries (from the query rewriter) and the department IDs (from the department router), and runs every query against every department.
2. For each pair, `HybridRetriever.retrieve()` in `retrieval/hybrid.py`:
   1. Gets the BM25 top 20 (jieba tokens, k1=1.5, b=0.75, department filter applied before the top-k cut) and the vector top 20.
   2. Merges them with **RRF** (reciprocal rank fusion): each chunk scores the sum of `1/(60+rank+1)` over both lists. The top `max(2k, 10)` are kept.
   3. **Reranks** with the bge-reranker-v2-m3 CrossEncoder (falling back to a keyword-based heuristic reranker) and returns the top 5.
3. Removes duplicates across queries and departments.
4. Fetches each full chunk from Mongo and checks that its parent document is still `active`, so archived versions never leak into answers.
5. Adds `doc_title` and returns the top k.

The orchestrator then passes these chunks to `AnswerAgent`, which writes a cited answer, and `VerifierAgent` checks it.

## Known weak points

- **`MongoVectorStore.search` scans every vector.** It loads all vectors for the department into Python and computes dot products, so each query is O(N) and pulls 1024-dim vectors over the network. This is fine for a demo but will not scale. The next step would be Atlas Vector Search or Milvus.
- **`SharedBM25Index.search` rebuilds the whole BM25 index on every query.** It calls `list_active_chunks()`, which scans `documents` and `chunks`, once per query per department. `BM25Index.search` itself loops over every document for each query token (`toks.count`).
- **`memory` mode re-embeds every chunk at startup.** This gets slow with bge-m3 on CPU as the corpus grows.
- **There is no context expansion.** `section_path` and neighbouring chunks are stored but not used to widen the context; retrieval works purely at chunk level.
- **Conflict-detector thresholds do not match their comment.** The comment says cosine > 0.85 and overlap > 0.3, but the code uses 0.5 and 0.15.
