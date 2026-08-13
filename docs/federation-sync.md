---
title: Federation and Sync
type: concept
created: 2026-05-16
updated: 2026-05-16
curation: agent
protected: false
source_policy: advisory
tags: [federation, sync]
sources: []
related: [architecture-overview]
visibility: public
---

# Federation and Synchronization

The Federation module enables multi-brain operability.

## Mechanisms
- **3-Way Task Merge**: Handles conflicts when tasks are modified in multiple federated nodes concurrently.
- **Federated Locks**: Validates agent task locks across distributed environments.
- **Git Sync**: Utilizes Git operations under the hood for artifact and state synchronization.
