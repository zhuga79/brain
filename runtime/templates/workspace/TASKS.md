# Local Tasks

<!--
  depends_on syntax (canonical): depends_on: [task-id-1, task-id-2, ...]
  - a bracketed, comma-separated list of task ids that must be done first
  - bare forms are also accepted: `depends_on: task-a` and `depends_on: task-a, task-b`
  - empty list [] is valid (no dependencies); an empty value is the same
  - an unbalanced bracket ([task-a) is rejected
  - empty components are rejected: [,] [dep,] [,dep] [dep,,other] task-a,,task-b
  - the field may appear only once per task; duplicates are rejected
  - next skips tasks not in [ ] and tasks with unmet deps
  - take/complete reject unmet deps with no mutation; already [x] is fail-closed
-->

- [ ] [P1] local-001 - Describe the first local task
      role: developer
      acceptance: State the concrete completion check.

- [ ] [P2] local-002 - Second task depending on first
      role: developer
      depends_on: [local-001]
      acceptance: Runs after local-001 is done.
