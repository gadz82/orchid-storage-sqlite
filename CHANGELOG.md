# Changelog

## [Unreleased]

## [1.0.0] - TBD

### Added

- `OrchidSQLiteChatStorage`, `OrchidSQLiteConfigStorage`,
  `OrchidSQLiteMCPTokenStore`,
  `OrchidSQLiteMCPClientRegistrationStore`,
  `OrchidSQLiteMCPGatewayStateStore` and
  `OrchidSQLiteIngestionManifest` extracted from `orchid-ai` core.
- `SQLiteEventStorage` (+ four narrow stores) and `SQLiteSignalQueue`
  extracted from `orchid-ai` core.
- SQLite schema migrations v001 (all framework-owned tables) and v002
  (ingestion manifest) with the `SQLiteMigrationRunner`.
- SQLite visibility fragment for `build_run_filter_clause`,
  auto-registered via the `orchid.visibility_fragments` entry-point group.
- Async SQLite LangGraph checkpointer, auto-registered as the `sqlite`
  type via the `orchid.checkpointers` entry-point group.
