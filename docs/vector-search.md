---
title: Vector Search Engine
type: concept
created: 2026-05-16
updated: 2026-05-16
curation: agent
protected: false
source_policy: advisory
tags: [search, vector]
sources: []
related: [architecture-overview]
visibility: public
---

# Vector Search Engine

Brain uses a Vector Search Engine for semantic retrieval of tasks, memory, and wiki pages.

## Features
- **Hybrid RRF Search**: Combines BM25 and Vector search results using Reciprocal Rank Fusion.
- **JSON Search Output**: Allows programmatic integration via `brain-vector` CLI.
- **Direct Index Rebuild**: Ensures index health and clears stale entries.
- **MCP Tools**: Integrates seamlessly with `tools_index` for context retrieval.
