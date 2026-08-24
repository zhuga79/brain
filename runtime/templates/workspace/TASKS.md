# Local Tasks

- [ ] [P1] local-001 - Describe the first local task
      role: developer
      acceptance: State the concrete completion check.

- [ ] [P2] local-002 - Second task depending on first
      role: developer
      depends_on: [local-001]
      acceptance: Runs after local-001 is done.
