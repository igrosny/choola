# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Add `Router` core node — declarative value-equality branch picker that wraps the existing `__active_branches__` engine mechanism
- Add parallel execution: the engine now runs independent DAG branches concurrently via a dynamic ready-queue scheduler, with fail-fast sibling cancellation on error
- Add tests covering parallel execution speedup, fail-fast cancellation, router routing variants, and conditional+parallel mixed patterns

### Changed
- Consolidate the CLI and server executors into a single `choola.engine.execute_dag` so `choola run` and the HTTP `/api/workflows/<name>/run` path share one code path; the CLI now properly honours `__active_branches__`, multi-parent merge, and `context["parent_outputs"]`
- Refactor the `bank-statement` workflow to use the new `Router` core node — split the old `check_duplicate` node into `hash_pdf` (single-job hash + dedup decision) and `dedup_router` (declarative routing)

### Fixed
- Wire `upload_form` to `hash_pdf` so the bank-statement workflow actually runs its dedup step (the previous `next_nodes = ["analyze_statement"]` bypassed it entirely)

## [0.9.0] - 2026-05-11

### Added
- Add Google Sheets core node for reading, appending, updating, and clearing ranges via the Sheets API
- Add multi-scope Google OAuth2 support: scope catalog endpoint, scope checklist in the credentials modal, and per-credential scope tracking so re-authorizing extends rather than replaces granted access

### Changed
- Default classifier-style nodes (yes/no, fixed-label, sentiment, intent) to extend the LLML core node so repeat patterns hit the local XGBoost cache instead of paid LLM calls

### Fixed
- Replace the retired Google OOB OAuth flow in `choola credential` with a pointer to the server's browser flow; the OOB redirect URI Google removed in 2022 no longer returns a usable code

### Infrastructure
- Add test suite covering the database layer, evaluations, token telemetry, base node helpers, core nodes, and the workflow engine

## [0.8.0] - 2026-04-20

### Added
- Add MCP server with JSON-RPC endpoint that exposes workflows as tools, including authentication support
- Add `dream` CLI command for training XGBoost classifiers and implement LLML node logic

## [0.7.0] - 2026-04-19

### Added
- Add terminal functionality to the workflow editor via a new `TerminalPanel` component with WebSocket support, scoped to the active workflow
- Add `explain` CLI command for explaining workflow context
- Add Claude Code template (`_claude/`) copied to end-user projects on `choola init`, including pre-approved settings and `/node`, `/workflow`, `/debug`, `/replay` slash commands

### Infrastructure
- Add `llms.txt` for unified AI agent instructions and enhance documentation

## [0.6.0] - 2026-04-18

### Added
- Add ChromaDB vector database integration for workflows: new `VectorDB` core node, `files/chroma/` per-workflow storage, and `vector_add` / `vector_query` / `vector_get` / `vector_delete` / `vector_count` helpers on `BaseNode`
- Add VectorDB schema and query API endpoints (`/api/workflows/<name>/vectordb/schema`, `/api/workflows/<name>/vectordb/query`) with a matching VectorDB tab in the workflow editor
- Add Evaluations tab to the workflow editor: paginated run list with status, duration, and token counts, plus a collapsible JSON detail view with per-node input/output/error inspection and Copy/Download actions
- Add evaluation API endpoints (`/api/workflows/<name>/evaluations`, `/api/workflows/<name>/evaluations/<run_id>`) that return summaries-only for listing and full JSON for detail
- Add LLM token telemetry: `BaseNode.report_tokens()` sidechannel feeds a per-run tally and is persisted in `run_logs` (new `prompt_tokens` / `completion_tokens` columns) and evaluation JSON
- Add engine-level cost circuit breaker enforcing two globals — `max_tokens_per_run` (per-run cap) and `max_tokens_per_hour` (rolling-hour cap across all runs); a breach raises `TokenLimitExceeded` and aborts the run
- Instrument the core `LLM` node to report Claude `usage.input_tokens`/`output_tokens` and Gemini `usage_metadata.prompt_token_count`/`candidates_token_count`

### Frontend
- Update logo styles in `AuthPage` and `WorkflowsPage` for improved aesthetics

## [0.5.0] - 2026-04-18

### Added
- Add SQLite database support for workflows with introspection and query capabilities
- Add branching, merging, and conditional routing to the workflow engine

## [0.4.0] - 2026-04-17

### Added
- Add HTTP node for making external requests with customizable parameters
- Add `replay` CLI command to execute a single node with saved input from evaluations
- Add interactive `credentials` CLI command with OAuth2 support for multiple providers

### Changed
- Enhance OAuth2 integration to support multiple providers and update frontend for provider selection
- Improve auto-layout for nodes in API responses

### Fixed
- Fix static file directory path to include `dist` subdirectory

### Infrastructure
- Update README getting started section and workflow execution details
- Update workflow documentation

## [0.3.0] - 2026-04-15

### Added
- Add evaluation storage system: every workflow run saves a JSON file to `workflows/<name>/evaluations/<run_id>.json` with per-node inputs, outputs, timing, and errors for debugging

### Changed
- Rename `tmp/` directory convention to `files/` for binary/generated files
- Add `files/` directory to `choola create` scaffold
- Add binary data rule to node contract: nodes must never put binary content in the payload

### Fixed
- Fix `payload_in` bug in execution engine where node input was incorrectly captured after execution instead of before

### Infrastructure
- Consolidate development guides into CLAUDE.md and create core node reference

## [0.2.1] - 2026-04-08

### Infrastructure
- Update workflow node contract documentation to include `static/` and `tmp/` directory guidelines.

## [0.2.0] - 2026-04-07

### Added
- Initial release of the `choola` pip package
- Core node types: `WebhookTrigger`, `FormTrigger`, `LLM` (Claude & Gemini)
- CLI commands: `init`, `start`, `create`, `list`, `run`, `nodes`
- SQLite-backed credential store with `GET/POST/DELETE /api/credentials` API
- Server (`choola/server.py`) and database (`choola/database.py`) as installable package modules
- `pyproject.toml` for package configuration and distribution
- Apache License 2.0


### Frontend
- Workflow editor (`WorkflowEditor.jsx`) with node palette, drag-and-drop canvas, and chat panel
- `WorkflowsPage` component with workflow list, search, and create modal
- `CredentialsModal` for managing API credentials with OAuth2 support
- `AuthPage` for authentication flow
- Design tokens and shared styles in `index.css`

### Infrastructure
- Google OAuth2 flow for credential management (used by `SaveToDrive` node)
- Vite proxy routes for local API development
- Refactored all workflow node imports to use the `choola` namespace
- README with project description, installation instructions, and quick start guide
