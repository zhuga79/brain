---
title: Architecture Overview
type: concept
created: 2026-05-16
updated: 2026-05-27
curation: agent
protected: false
source_policy: advisory
tags: [architecture, core]
sources: []
related: [federation-sync, skill-curator, vector-search, security-handoffs, learning-loop]
visibility: public
---

# Architecture Overview

Brain is a local memory, task, and role orchestration system for LLM agents.

## Key Components
- **Orchestrator**: Core execution engine handling task lifecycles, locks, handoffs, and council partial synthesis.
- **Dashboard & Operator Console**: Visual UI for monitoring, token economy metrics, and manual intervention.
- **Federation**: [[federation-sync|Multi-brain synchronization]], 3-way task merging, and federated locks.
- **Skill Curator**: [[skill-curator|Autonomous discovery and JIT injection]] of skills (Opencode, Kilocode).
- **Vector Search Engine**: [[vector-search|Hybrid retrieval]] over memory, tasks, and wiki.
- **Security & Handoffs**: [[security-handoffs|Secret boundaries, fallback payloads, and webhook formatters]].
- **Learning Loop**: [[learning-loop|Operational feedback capture]] from failures, human edits, and phase reviews.
