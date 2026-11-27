# Persistent Instrument Registry (`InstrumentRegistry`)

## Architecture
`InstrumentRegistry` (`ml_data/instruments/registry.py`) wraps `SQLiteInstrumentRepository` (`ml_data/instruments/repository.py`) using Python's standard `sqlite3` in WAL mode with `PRAGMA foreign_keys = ON` and an `RLock` for safe concurrent reads and serialized transactional writes.

## Database Structure (Schema Version 1)
1. `schema_migrations(version, applied_at)` — tracks forward-only schema migrations.
2. `instruments(...)` — canonical instrument table keyed by `instrument_id`, indexed by `market`, `asset_class`, `segment`, `(exchange, trading_symbol)`, `underlying_instrument_id`, `expiry_date`, and `(instrument_status, is_active)`. Expired and delisted instruments are retained permanently.
3. `instrument_spec_versions(...)` — append-only historical contract specification table. Whenever `Instrument.spec_dict()`'s SHA-256 `spec_hash` changes on `upsert()`, the previous active row's `effective_to` is closed and a new version row is inserted.
4. `provider_mappings(...)` — maps external `(provider, provider_exchange, provider_symbol, provider_instrument_id)` to a canonical `instrument_id`. Ambiguous mappings attempting to bind an already-mapped provider identifier to a different `instrument_id` raise `RegistryConflictError`.

## Registry API
- `register(instrument, mappings=None)` / `upsert(instrument, mappings=None)`
- `add_provider_mapping(mapping)` / `get_provider_mappings(instrument_id)` / `resolve_provider_symbol(provider, symbol, exchange=None)`
- `get(instrument_id)` / `get_by_exchange_symbol(exchange, trading_symbol)`
- `list_by_market(market)` / `list_by_asset_class(asset_class)` / `list_by_segment(segment)`
- `list_by_underlying(underlying_id)` / `list_by_expiry(expiry_date)`
- `list_active()` / `list_expired()`
- `get_options_for_underlying(underlying_id)` / `get_futures_for_underlying(underlying_id)`
- `get_spec_history(instrument_id)`
- `export_json()` / `import_json(payload)`

## Adding a New Exchange or Provider
1. Implement `InstrumentAdapter` (`ml_data/adapters/base.py`) returning `List[InstrumentCandidate]`.
2. Normalize provider symbols/contract specs into canonical `Instrument` + `ProviderInstrumentMapping` instances.
3. Upsert candidates into `InstrumentRegistry` (idempotent; spec changes automatically versioned).
4. Keep universe selection separate from the registry.
