# Local Tasks

<!--
  depends_on syntax: depends_on: [task-id-1, task-id-2, ...]
  - bracketed, comma-separated list of task ids that must be done first
  - empty components are rejected: [,] [dep,] [,dep] [dep,,other]
  - the field may appear only once per task; duplicates are rejected
  - next skips tasks with unmet deps; take/complete reject with no mutation
-->

- [ ] [P1] local-001 - Describe the first local task
      role: developer
      acceptance: State the concrete completion check.

- [ ] [P2] local-002 - Second task depending on first
      role: developer
      depends_on: [local-001]
      acceptance: Runs after local-001 is done.
