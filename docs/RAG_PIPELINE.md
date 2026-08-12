# RAG Pipeline

## Purpose

The RAG service answers only from the selected course. It keeps source locations through extraction and chunking so every useful answer can show filenames, page/slide/section locators, and excerpts.

## Ingestion flow

1. api/ingestion.py receives a multipart file and reads at most MAX_UPLOAD_BYTES + 1.
2. IngestionService.queue_document validates course existence, filename, extension, byte size, basic signature, and SHA-256 uniqueness.
3. The service stores a generated filename under data/uploads/<course_id>; the client filename is metadata only.
4. A documents row and queued ingestion_jobs row are created before background processing.
5. IngestionService.process_document marks both records processing and calls load_document.
6. loaders.py returns SourceSection values with content and a page, slide, section, paragraph, or line locator.
7. chunk_sections keeps paragraph boundaries where possible, word-splits oversized blocks, and carries a bounded overlap.
8. The configured EmbeddingProvider embeds batches of at most 10 inputs. Production uses OpenAIEmbeddingProvider; repeatable tests use DeterministicEmbeddingProvider.
9. chunks are inserted transactionally. SQLite triggers mirror their content into chunks_fts.
10. Document and job states become ready/completed with the exact chunk count. Exceptions roll back the chunk replacement and produce failed states.

Supported ingestion types are PDF, Markdown, TXT, DOCX, and PPTX. Legacy PPT, spreadsheets, notebooks, GML, and course data assets are inventory-only because treating them as prose would create misleading retrieval content.

## Scanned PDF policy

Textless PDFs fail with SCANNED_PDF_REQUIRES_OCR. For the supplied GE2324 assignment_2.pdf, a manually verified transcription is versioned in data/transcriptions under the source SHA-256. The corpus importer applies it only when the inventory checksum matches, then reruns normal extraction/chunk/embedding persistence. This makes OCR remediation reviewable and prevents a sidecar from being attached to a different file.

## Retrieval flow

1. QaService.require_course rejects an unknown course before streaming starts.
2. QaService.stream creates a conversation and stores the user message.
3. HybridRetriever.retrieve embeds the question once.
4. ChunkRepository.keyword_search removes English function words, queries FTS5 using a safely constructed token expression, filters course_id, and orders BM25 candidates. An all-stopword question falls back to its original tokens.
5. ChunkRepository.vector_search loads only that course's chunks, parses stored vectors, and ranks cosine similarity.
6. reciprocal_rank_fusion combines lexical and semantic ranks using weighted reciprocal rank fusion. Keyword ranks use weight 1.0 and vector ranks use 0.15, so a strong source-text match stays grounded while a cross-channel semantic match still receives a boost. If FTS finds nothing, vector-only hits remain available. Duplicate chunks merge by ID.
7. build_context_with_hits labels and truncates the fused chunks to MAX_CONTEXT_CHARS.
8. AnswerProvider.stream_answer yields text. The OpenAI provider uses Responses streaming; the deterministic provider emits a stable extractive answer for tests.
9. QaService emits each citation as a separate SSE event, emits done, then persists the assembled assistant message and citations JSON.

The course filter exists in both candidate paths, not only after ranking. This is the central isolation invariant.

## Prompt contract

The prompt marks retrieved text as untrusted course material, instructs the model to use only that evidence, and requires a clear insufficiency response when support is missing. Source labels are stable and citations come from server-side hits rather than model-invented filenames.

## SSE contract

- event: meta — conversationId.
- event: delta — a text fragment.
- event: citation — sourceId, filename, locatorType, locatorValue, excerpt, and fused score.
- event: done — completion marker.
- event: error — controlled stream failure when possible.

The browser parser handles frames separated by a blank line and incrementally updates one assistant message.

## Corpus acceptance questions

Use these after any reimport:

| Course | Question | Expected evidence signal |
|---|---|---|
| CS3481 | How does DBSCAN identify a core point? | DBSCAN, epsilon/neighborhood, minimum-points material; no GE2324 source |
| CS3481 | Compare single-link and complete-link clustering. | linkage or hierarchical clustering notes; no GE2324 source |
| GE2324 | What is Spearman correlation used for? | rank correlation material; no CS3481 source |
| GE2324 | What does Assignment 2 ask students to do with K-means and colors? | assignment_2.pdf transcription and K-means/color evidence |
| GE2324 | How does MinHash estimate similarity? | MinHash/Jaccard material; no CS3481 source |

For each query verify a non-empty answer, at least one citation when evidence exists, selected-course filenames only, and a sensible locator. Also ask an intentionally unsupported question and confirm the service says evidence is insufficient rather than fabricating a citation.

## Tunable settings

| Setting | Default | Effect |
|---|---:|---|
| CHUNK_SIZE | 1200 | target characters per chunk |
| CHUNK_OVERLAP | 200 | context carried into the next chunk |
| TOP_K | 6 | fused hits returned to the prompt |
| MAX_CONTEXT_CHARS | 18000 | hard context budget |
| OPENAI_BASE_URL | empty | optional trusted OpenAI-compatible API endpoint |
| OPENAI_EMBEDDING_MODEL | text-embedding-3-small | production vector model |
| RAG_PROVIDER_MODE | openai | openai or deterministic |

The ingestion batch size is fixed at 10 to stay within the target synchronous embedding API limit. Changing the embedding model requires re-embedding the corpus. Changing only the answer model does not.
