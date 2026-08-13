# ADR-001: Dashboard Control-Plane Refactoring

**Date**: 2026-06-03

**Status**: Proposed

## Context

The current dashboard implementation (`runtime/bin/brain-dashboard` and `runtime/lib/brain_dashboard/render/html.py`) is a monolithic service that mixes several concerns:
- HTTP routing and request handling.
- Business logic for actions (launching tasks, importing workspaces).
- Data collection and snapshot management.
- HTML, CSS, and JavaScript rendering.

This makes the code difficult to maintain, test, and evolve. The principle of "truth lives in folders" is also violated by having a centralized component that knows too much about the underlying structure of the brain.

## Decision

We will refactor the dashboard into a set of well-defined, single-responsibility modules. This will improve separation of concerns, testability, and maintainability.

The new modular architecture will be composed of the following components:

-   **`dashboard_http`**: A thin web server layer responsible for HTTP routing, request/response handling, and authentication. It will delegate all business logic to other services. This will be the main entry point for the dashboard.
-   **`dashboard_actions`**: This service will encapsulate the logic for all user-initiated actions, such as launching tasks, probing providers, managing the task queue, running queue proposals, and invoking review/validate/index cycles. It will be called by the `dashboard_http` service.
-   **`workspace_service`**: This module will be responsible for all workspace-related operations, including discovering workspaces, parsing `BRAIN.md` and `TASKS.md` files, and handling workspace imports. It will enforce the principle that "truth lives in folders" by reading directly from the file system and not maintaining any central registry.
-   **`dashboard_snapshot`**: This service will be responsible for collecting data from various sources (for example, tasks, locks, providers) and creating a snapshot of the system's state. The `dashboard_http` service will use this to serve API requests and render the dashboard.
-   **`render_assets`**: A static asset boundary for CSS, JavaScript, and other browser assets. The rendered HTML will no longer contain inline CSS and JavaScript.
-   **Render sections**: HTML assembly will be split into small render modules for dashboard shell, task table/tree, manual launch, queue proposals, provider/status panels, search, scheduled work, and workspace import. These modules may format view data only; they must not call subprocesses, mutate tasks, or read workspace files directly.

## Folder-Native Truth and Allowed Caches

There will be no central document registry. Truth lives in folders:

- Brain queue truth lives in `tasks/active.md`, `tasks/done.md`, and lock files managed through Brain CLI.
- Workspace truth lives in each workspace folder: `BRAIN.md`, `TASKS.md`, `LOG.md`, and the source documents in that folder.
- Wiki truth lives in `wiki/` pages with the existing curation rules.

Allowed caches are rebuildable, non-authoritative, and safe to delete:

- Search index: BM25/vector/search documents built from folder/wiki/raw sources.
- Launch proposals: control-plane suggestions for what can be run next; they never become task truth until accepted through task/launch APIs.
- Dashboard snapshot: short-lived view data assembled from task files, locks, provider state, index health, and workspace files.

If a cache conflicts with folder files, folder files win. The repair path is rebuild, not manual cache editing.

## Current Workspace-Import Mapping

The recent workspace-import work maps to the new boundaries as follows:

- Descriptor reading and normalization belongs in `workspace_service`.
- Folder conversion (`BRAIN.md` and `TASKS.md` creation/update) belongs in `workspace_service`.
- Auto role assignment and local task decomposition belong in `workspace_service`, backed by the canonical task parser.
- Per-workspace CLI/model/effort choices are dashboard control-plane state and belong behind `dashboard_actions`; they must not turn into a document registry.
- Import UI rendering belongs in render sections plus `render_assets`; import POST handling belongs in `dashboard_http`; import execution belongs in `workspace_service`.

The open workspace parser/task-id ticket (`t-2026-06-01-workspace-align-local-task-ids`) is the first implementation dependency under this plan because workspace import output must be launch-valid and canonical-parser-compatible before broader UI refactors.

## Consequences

### Positive

-   **Improved Maintainability**: Each module will have a single responsibility, making it easier to understand and modify.
-   **Improved Testability**: Each module can be tested in isolation.
-   **Clearer Boundaries**: The separation between the web layer, business logic, and data layer will be explicit.
-   **Reinforces "Truth in Folders"**: Folder files remain the source of truth. The `workspace_service` is only the access boundary that reads and writes those folder-native files.

### Negative

-   **Increased Complexity**: More modules mean more boilerplate code for communication between them.
-   **Migration Effort**: The existing codebase needs to be carefully migrated to the new architecture.

## Risks and Migration Plan

### Risks
-   **Breaking Changes**: The refactoring might introduce breaking changes to the dashboard's API.
-   **Migration Complexity**: The migration of the existing codebase could be complex and time-consuming.

### Migration Order
1.  **Workspace parser alignment**: complete `t-2026-06-01-workspace-align-local-task-ids` first so imported tasks have launch-valid stable IDs and use the canonical parser contract.
2.  **`render_assets` and render sections**: extract CSS/JavaScript and split passive HTML sections without changing behavior.
3.  **`workspace_service`**: create the workspace boundary for discovery, descriptor import, task decomposition, and folder conversion.
4.  **`dashboard_snapshot`**: centralize rebuildable view-data collection.
5.  **`dashboard_actions`**: extract task launch, queue proposal, provider probe, review-cycle, validate-cycle, and index-cycle actions.
6.  **`dashboard_http`**: finally, refactor `brain-dashboard` into a thin HTTP layer that validates requests and delegates to the other services.

## Test Migration Plan

- Preserve current dashboard smoke coverage before extraction; every module split starts with a no-behavior-change test.
- Add render-section tests that assert stable IDs, forms, details elements, output boxes, and action targets without requiring a running server.
- Add `workspace_service` unit tests for descriptor parsing, Cyrillic titles, stable ASCII task IDs, canonical `TASKS.md` discovery, and idempotent folder conversion.
- Add `dashboard_actions` tests with fake subprocess/Brain CLI adapters for launch, queue proposal, review-cycle, validate-cycle, and index-cycle actions.
- Add `dashboard_snapshot` tests for stale index reporting, lock/task/provider aggregation, and cache rebuild semantics.
- Keep HTTP smoke tests focused on routing, validation, auth, and JSON/HTML response wiring.

## Stop Rule

No new dashboard surface area should be added until the above boundaries exist for the touched area. Exceptions are allowed only for P0/P1 bug fixes, security fixes, or visible-feedback defects already in the Phase 27 queue. Any new dashboard capability must first state which boundary owns rendering, HTTP validation, action execution, snapshot data, workspace file access, and cache behavior.

## Implementation Tickets

Here are the first three tickets to start the implementation:

1.  **TICKET-1: Extract CSS and JavaScript from `html.py`**
    -   **Description**: Move all inline CSS and JavaScript from `runtime/lib/brain_dashboard/render/html.py` to separate `.css` and `.js` files.
    -   **Acceptance Criteria**:
        -   `html.py` contains no inline CSS or JavaScript.
        -   The dashboard serves the new static asset files.
        -   The dashboard's appearance and functionality remain unchanged.
    -   **Tests**:
        -   Visual regression tests to ensure the UI is unchanged.
        -   E2E tests to verify all interactive components still work.

2.  **TICKET-2: Create the `workspace_service` module**
    -   **Description**: Create a new `workspace_service` module that encapsulates all logic related to workspace discovery and management from `runtime/bin/brain-dashboard` and `runtime/lib/brain_workspace.py`.
    -   **Acceptance Criteria**:
        -   A new `workspace_service.py` file is created.
        -   The `discover_workspaces` and `import_workspace` logic is moved to this new service.
        -   `brain-dashboard` now calls the `workspace_service` for all workspace-related operations.
        -   The "truth lives in folders" principle is maintained.
    -   **Tests**:
        -   Unit tests for all functions in `workspace_service.py`.
        -   Integration tests to ensure `brain-dashboard` correctly interacts with the new service.

3.  **TICKET-3: Implement the `dashboard_snapshot` service**
    -   **Description**: Create a `dashboard_snapshot` service that is responsible for collecting all the data needed for the dashboard view.
    -   **Acceptance Criteria**:
        -   A new `dashboard_snapshot.py` file is created.
        -   The data collection logic from `brain-dashboard` and `brain_dashboard/data.py` is moved to this new service.
        -   The service provides a single function to get a complete snapshot of the dashboard data.
    -   **Tests**:
        -   Unit tests for the snapshot service.
        -   The snapshot data structure is validated against a schema.

4.  **TICKET-4: Extract dashboard action boundary**
    -   **Description**: Move task launch, queue proposal, provider probe, review-cycle, validate-cycle, and index-cycle execution out of `brain-dashboard` into `dashboard_actions`.
    -   **Acceptance Criteria**:
        -   HTTP handlers validate input and call `dashboard_actions`; they do not spawn subprocesses directly.
        -   Action functions expose typed success/error results that the dashboard can render consistently.
        -   Existing launch/queue/cycle behavior is preserved.
    -   **Tests**:
        -   Unit tests with fake command adapters for success, failure, timeout, and validation errors.
        -   Existing smoke cases for launch/queue/cycles continue to pass.
