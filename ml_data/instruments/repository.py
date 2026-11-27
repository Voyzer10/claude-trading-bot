"""SQLite persistence layer for the Universal Instrument Registry."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional

from .enums import AssetClass, Market
from .identity import IDENTITY_VERSION, build_instrument_id, compute_spec_hash
from .schemas import Instrument, InstrumentSpecVersion, ProviderInstrumentMapping

_MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS instruments (
        instrument_id TEXT PRIMARY KEY,
        schema_version TEXT NOT NULL,
        identity_version TEXT NOT NULL DEFAULT 'v2',
        market TEXT NOT NULL,
        asset_class TEXT NOT NULL,
        segment TEXT NOT NULL,
        exchange TEXT NOT NULL,
        canonical_symbol TEXT NOT NULL,
        trading_symbol TEXT NOT NULL,
        underlying_instrument_id TEXT,
        expiry_date TEXT,
        is_active INTEGER NOT NULL,
        is_tradable INTEGER NOT NULL,
        instrument_status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_instruments_mkt ON instruments(market);
    CREATE INDEX IF NOT EXISTS idx_instruments_ac ON instruments(asset_class);
    CREATE INDEX IF NOT EXISTS idx_instruments_seg ON instruments(segment);
    CREATE INDEX IF NOT EXISTS idx_instruments_ex_sym ON instruments(exchange, trading_symbol);
    CREATE INDEX IF NOT EXISTS idx_instruments_und ON instruments(underlying_instrument_id);
    CREATE INDEX IF NOT EXISTS idx_instruments_exp ON instruments(expiry_date);
    CREATE INDEX IF NOT EXISTS idx_instruments_status ON instruments(instrument_status, is_active);

    CREATE TABLE IF NOT EXISTS instrument_spec_versions (
        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
        instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
        effective_from TEXT NOT NULL,
        effective_to TEXT,
        spec_hash TEXT NOT NULL,
        spec_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_spec_inst_eff ON instrument_spec_versions(instrument_id, effective_from);

    CREATE TABLE IF NOT EXISTS provider_mappings (
        mapping_id TEXT PRIMARY KEY,
        instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
        provider TEXT NOT NULL,
        provider_instrument_id TEXT,
        provider_symbol TEXT NOT NULL,
        provider_exchange TEXT NOT NULL DEFAULT '',
        provider_feed TEXT NOT NULL DEFAULT '',
        valid_from TEXT,
        valid_until TEXT,
        last_verified_at TEXT,
        is_primary INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_pm_inst ON provider_mappings(instrument_id);
    CREATE INDEX IF NOT EXISTS idx_pm_lookup ON provider_mappings(provider, provider_symbol, provider_exchange, provider_feed);
    CREATE INDEX IF NOT EXISTS idx_pm_ext_id ON provider_mappings(provider, provider_instrument_id, provider_exchange);
    """,
    2: """
    CREATE TABLE IF NOT EXISTS instrument_spec_versions_v2 (
        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
        instrument_id TEXT NOT NULL REFERENCES instruments(instrument_id) ON DELETE RESTRICT,
        effective_from TEXT,
        effective_to TEXT,
        spec_hash TEXT NOT NULL,
        spec_json TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    );
    INSERT INTO instrument_spec_versions_v2 (
        version_id, instrument_id, effective_from, effective_to, spec_hash, spec_json, recorded_at
    )
    SELECT version_id, instrument_id, effective_from, effective_to, spec_hash, spec_json, recorded_at
    FROM instrument_spec_versions;
    DROP TABLE instrument_spec_versions;
    ALTER TABLE instrument_spec_versions_v2 RENAME TO instrument_spec_versions;
    CREATE INDEX IF NOT EXISTS idx_spec_inst_eff ON instrument_spec_versions(instrument_id, effective_from);
    """,
}

_ALLOWED_UNDERLYING_CLASSES = {
    (Market.US, AssetClass.OPTION): {AssetClass.EQUITY, AssetClass.ETF, AssetClass.INDEX},
    (Market.US, AssetClass.FUTURE): {AssetClass.INDEX, AssetClass.EQUITY, AssetClass.ETF},
    (Market.IN, AssetClass.OPTION): {AssetClass.INDEX},
    (Market.IN, AssetClass.FUTURE): {AssetClass.INDEX},
    (Market.CRYPTO, AssetClass.CRYPTO_FUTURE): {AssetClass.CRYPTO_SPOT},
    (Market.CRYPTO, AssetClass.CRYPTO_PERPETUAL): {AssetClass.CRYPTO_SPOT},
}


class RegistryError(RuntimeError):
    """Base error for registry persistence operations."""


class RegistryConflictError(RegistryError):
    """Raised when a provider mapping or registration conflicts with an existing canonical identity."""


def _parse_opt_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    dt = datetime.fromisoformat(val)
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _intervals_overlap(
    a_from: Optional[datetime],
    a_until: Optional[datetime],
    b_from: Optional[datetime],
    b_until: Optional[datetime],
) -> bool:
    """Return True if half-open intervals [a_from, a_until) and [b_from, b_until) overlap."""
    cond1 = a_from is None or b_until is None or a_from < b_until
    cond2 = b_from is None or a_until is None or b_from < a_until
    return cond1 and cond2


class SQLiteInstrumentRepository:
    """Thread-safe, transactional SQLite repository with schema migrations and spec history."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON;")
            if db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 30000;")
            self._migrate()

    def _migrate(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        cur = self._conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        current = int(cur.fetchone()[0])
        now = datetime.now(timezone.utc).isoformat()
        for ver in sorted(_MIGRATIONS):
            if ver > current:
                self._conn.executescript(_MIGRATIONS[ver])
                self._conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (ver, now)
                )
        self._conn.commit()

    def schema_version(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            return int(cur.fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _validate_underlying_tx(self, inst: Instrument) -> None:
        if not inst.underlying_instrument_id:
            return
        row = self._conn.execute(
            "SELECT payload_json FROM instruments WHERE instrument_id = ?",
            (inst.underlying_instrument_id,),
        ).fetchone()
        if row is None:
            raise RegistryError(f"Unknown underlying_instrument_id: {inst.underlying_instrument_id}")
        und = Instrument.from_json(row["payload_json"])
        if und.market != inst.market:
            raise RegistryConflictError(
                f"Underlying market {und.market.value} incompatible with derivative market {inst.market.value}"
            )
        allowed = _ALLOWED_UNDERLYING_CLASSES.get((inst.market, inst.asset_class))
        if allowed is not None and und.asset_class not in allowed:
            raise RegistryConflictError(
                f"Underlying asset_class {und.asset_class.value} invalid for {inst.market.value} {inst.asset_class.value}"
            )

    def _check_mapping_conflict(self, m: ProviderInstrumentMapping) -> None:
        prov = m.provider.strip().lower()
        ex = (m.provider_exchange or "").strip().upper()
        feed = (m.provider_feed or "").strip().lower()
        rows = self._conn.execute(
            """
            SELECT instrument_id, valid_from, valid_until FROM provider_mappings
            WHERE LOWER(provider) = ? AND UPPER(provider_exchange) = ? AND provider_symbol = ? AND LOWER(provider_feed) = ?
              AND instrument_id != ?
            """,
            (prov, ex, m.provider_symbol, feed, m.instrument_id),
        ).fetchall()
        for r in rows:
            if _intervals_overlap(m.valid_from, m.valid_until, _parse_opt_dt(r["valid_from"]), _parse_opt_dt(r["valid_until"])):
                raise RegistryConflictError(
                    f"Overlapping provider mapping: ({prov}, {ex}, {m.provider_symbol}, {feed}) "
                    f"conflicts with {r['instrument_id']}"
                )
        if m.provider_instrument_id:
            rows2 = self._conn.execute(
                """
                SELECT instrument_id, valid_from, valid_until FROM provider_mappings
                WHERE LOWER(provider) = ? AND UPPER(provider_exchange) = ? AND provider_instrument_id = ?
                  AND instrument_id != ?
                """,
                (prov, ex, m.provider_instrument_id, m.instrument_id),
            ).fetchall()
            for r in rows2:
                if _intervals_overlap(m.valid_from, m.valid_until, _parse_opt_dt(r["valid_from"]), _parse_opt_dt(r["valid_until"])):
                    raise RegistryConflictError(
                        f"Overlapping provider_instrument_id: ({prov}, {ex}, {m.provider_instrument_id}) "
                        f"conflicts with {r['instrument_id']}"
                    )

    def _upsert_mapping_tx(self, m: ProviderInstrumentMapping) -> None:
        self._check_mapping_conflict(m)
        prov = m.provider.strip().lower()
        ex = (m.provider_exchange or "").strip().upper()
        feed = (m.provider_feed or "").strip().lower()
        self._conn.execute(
            """
            INSERT INTO provider_mappings (
                mapping_id, instrument_id, provider, provider_instrument_id,
                provider_symbol, provider_exchange, provider_feed,
                valid_from, valid_until, last_verified_at, is_primary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mapping_id) DO UPDATE SET
                provider_feed = excluded.provider_feed,
                valid_from = excluded.valid_from,
                valid_until = excluded.valid_until,
                last_verified_at = excluded.last_verified_at,
                is_primary = excluded.is_primary
            """,
            (
                m.mapping_id,
                m.instrument_id,
                prov,
                m.provider_instrument_id,
                m.provider_symbol,
                ex,
                feed,
                m.valid_from.isoformat() if m.valid_from else None,
                m.valid_until.isoformat() if m.valid_until else None,
                m.last_verified_at.isoformat() if m.last_verified_at else None,
                1 if m.is_primary else 0,
            ),
        )

    def upsert_instrument(
        self,
        instrument: Instrument,
        mappings: Optional[List[ProviderInstrumentMapping]] = None,
        *,
        allow_update: bool = True,
        validate_underlying: bool = True,
    ) -> Instrument:
        expected_id = build_instrument_id(
            market=instrument.market,
            asset_class=instrument.asset_class,
            exchange=instrument.exchange,
            canonical_symbol=instrument.canonical_symbol,
            clearing_exchange=instrument.clearing_exchange,
            underlying_instrument_id=instrument.underlying_instrument_id,
            expiry_date=instrument.expiry_date,
            strike_price=instrument.strike_price,
            option_right=instrument.option_right,
            contract_type=instrument.contract_type,
            contract_multiplier=instrument.contract_multiplier,
            deliverable_shares=instrument.deliverable_shares,
            deliverable_type=instrument.deliverable_type,
            base_currency=instrument.base_currency,
            quote_currency=instrument.quote_currency,
            settlement_currency=instrument.settlement_currency,
            is_inverse=instrument.is_inverse,
        )
        if instrument.instrument_id != expected_id:
            raise RegistryConflictError(
                f"Canonical ID mismatch: {instrument.instrument_id!r} != {expected_id!r}"
            )

        spec_payload = instrument.spec_dict()
        spec_hash = compute_spec_hash(spec_payload)
        spec_json = json.dumps(spec_payload, sort_keys=True, separators=(",", ":"))
        recorded_dt = datetime.now(timezone.utc)
        recorded_iso = recorded_dt.isoformat()
        eff_dt = instrument.effective_from.astimezone(timezone.utc) if instrument.effective_from else None

        with self._lock:
            with self._conn:
                if validate_underlying:
                    self._validate_underlying_tx(instrument)

                existing = self._conn.execute(
                    "SELECT created_at, payload_json FROM instruments WHERE instrument_id = ?",
                    (instrument.instrument_id,),
                ).fetchone()
                if existing is not None and not allow_update:
                    raise RegistryConflictError(f"Instrument already registered: {instrument.instrument_id}")

                if existing is not None:
                    prev = Instrument.from_json(existing["payload_json"])
                    if (
                        prev.market != instrument.market
                        or prev.asset_class != instrument.asset_class
                        or prev.exchange != instrument.exchange
                        or prev.canonical_symbol != instrument.canonical_symbol
                    ):
                        raise RegistryConflictError(
                            f"Cannot overwrite immutable identity fields for {instrument.instrument_id}"
                        )
                    d = instrument.to_dict()
                    d["created_at"] = prev.created_at.isoformat()
                    stored = Instrument.from_dict(d)
                else:
                    stored = instrument

                payload_json = stored.to_json()
                self._conn.execute(
                    """
                    INSERT INTO instruments (
                        instrument_id, schema_version, identity_version, market, asset_class, segment,
                        exchange, canonical_symbol, trading_symbol, underlying_instrument_id,
                        expiry_date, is_active, is_tradable, instrument_status,
                        created_at, updated_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(instrument_id) DO UPDATE SET
                        schema_version = excluded.schema_version,
                        identity_version = excluded.identity_version,
                        market = excluded.market,
                        asset_class = excluded.asset_class,
                        segment = excluded.segment,
                        exchange = excluded.exchange,
                        canonical_symbol = excluded.canonical_symbol,
                        trading_symbol = excluded.trading_symbol,
                        underlying_instrument_id = excluded.underlying_instrument_id,
                        expiry_date = excluded.expiry_date,
                        is_active = excluded.is_active,
                        is_tradable = excluded.is_tradable,
                        instrument_status = excluded.instrument_status,
                        updated_at = excluded.updated_at,
                        payload_json = excluded.payload_json
                    """,
                    (
                        stored.instrument_id,
                        stored.schema_version,
                        stored.identity_version or IDENTITY_VERSION,
                        stored.market.value,
                        stored.asset_class.value,
                        stored.segment.value,
                        stored.exchange,
                        stored.canonical_symbol,
                        stored.trading_symbol,
                        stored.underlying_instrument_id,
                        stored.expiry_date.isoformat() if stored.expiry_date else None,
                        1 if stored.is_active else 0,
                        1 if stored.is_tradable else 0,
                        stored.instrument_status.value,
                        stored.created_at.isoformat(),
                        stored.updated_at.isoformat(),
                        payload_json,
                    ),
                )

                # Historical specification versioning: append only when spec_hash changes
                self._record_spec_version_tx(stored.instrument_id, eff_dt, spec_hash, spec_json, recorded_iso)

                for m in mappings or ():
                    if m.instrument_id != stored.instrument_id:
                        raise RegistryConflictError(
                            f"Mapping instrument_id {m.instrument_id} does not match {stored.instrument_id}"
                        )
                    self._upsert_mapping_tx(m)
            return stored

    def _record_spec_version_tx(
        self,
        instrument_id: str,
        eff_dt: Optional[datetime],
        spec_hash: str,
        spec_json: str,
        recorded_iso: str,
    ) -> None:
        rows = self._conn.execute(
            "SELECT * FROM instrument_spec_versions WHERE instrument_id = ? ORDER BY version_id ASC",
            (instrument_id,),
        ).fetchall()
        if not rows:
            self._conn.execute(
                """
                INSERT INTO instrument_spec_versions (
                    instrument_id, effective_from, effective_to, spec_hash, spec_json, recorded_at
                ) VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (instrument_id, eff_dt.isoformat() if eff_dt else None, spec_hash, spec_json, recorded_iso),
            )
            return

        # Idempotent if current open version already has the exact same spec_hash
        open_rows = [r for r in rows if r["effective_to"] is None]
        latest = open_rows[-1] if open_rows else rows[-1]
        if latest["spec_hash"] == spec_hash and (eff_dt is None or _parse_opt_dt(latest["effective_from"]) == eff_dt):
            return

        prev_eff = _parse_opt_dt(latest["effective_from"])
        if eff_dt is None:
            # Unknown effective date: never fabricate effective_to or effective_from
            self._conn.execute(
                """
                INSERT INTO instrument_spec_versions (
                    instrument_id, effective_from, effective_to, spec_hash, spec_json, recorded_at
                ) VALUES (?, NULL, NULL, ?, ?, ?)
                """,
                (instrument_id, spec_hash, spec_json, recorded_iso),
            )
            return

        # Dated spec version: check for duplicate effective_from
        dated_rows = sorted(
            [(r, _parse_opt_dt(r["effective_from"]), _parse_opt_dt(r["effective_to"])) for r in rows if r["effective_from"]],
            key=lambda x: x[1],
        )
        for _, r_from, _ in dated_rows:
            if r_from == eff_dt:
                raise RegistryConflictError(
                    f"Specification version already exists at effective_from={eff_dt.isoformat()} for {instrument_id}"
                )

        if prev_eff is None or eff_dt > prev_eff:
            # Normal forward progression (or closing an unknown-start initial record)
            if latest["effective_to"] is None:
                self._conn.execute(
                    "UPDATE instrument_spec_versions SET effective_to = ? WHERE version_id = ?",
                    (eff_dt.isoformat(), latest["version_id"]),
                )
            self._conn.execute(
                """
                INSERT INTO instrument_spec_versions (
                    instrument_id, effective_from, effective_to, spec_hash, spec_json, recorded_at
                ) VALUES (?, ?, NULL, ?, ?, ?)
                """,
                (instrument_id, eff_dt.isoformat(), spec_hash, spec_json, recorded_iso),
            )
            return

        # Backdated historical specification: eff_dt < prev_eff
        next_eff: Optional[datetime] = None
        for r, r_from, r_to in dated_rows:
            if r_from > eff_dt:
                next_eff = r_from
                break
            if r_to is None or r_to > eff_dt:
                self._conn.execute(
                    "UPDATE instrument_spec_versions SET effective_to = ? WHERE version_id = ?",
                    (eff_dt.isoformat(), r["version_id"]),
                )
        if next_eff is not None and next_eff <= eff_dt:
            raise RegistryConflictError(f"Invalid backdated spec interval: {eff_dt} >= {next_eff}")
        self._conn.execute(
            """
            INSERT INTO instrument_spec_versions (
                instrument_id, effective_from, effective_to, spec_hash, spec_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                instrument_id,
                eff_dt.isoformat(),
                next_eff.isoformat() if next_eff else None,
                spec_hash,
                spec_json,
                recorded_iso,
            ),
        )

    def add_mapping(self, mapping: ProviderInstrumentMapping) -> None:
        with self._lock:
            with self._conn:
                exists = self._conn.execute(
                    "SELECT 1 FROM instruments WHERE instrument_id = ?", (mapping.instrument_id,)
                ).fetchone()
                if exists is None:
                    raise RegistryError(f"Unknown canonical instrument_id: {mapping.instrument_id}")
                self._upsert_mapping_tx(mapping)

    def get(self, instrument_id: str) -> Optional[Instrument]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM instruments WHERE instrument_id = ?", (instrument_id,)
            ).fetchone()
            return Instrument.from_json(row["payload_json"]) if row else None

    def query(self, where_sql: str = "1=1", params: tuple = ()) -> List[Instrument]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT payload_json FROM instruments WHERE {where_sql} ORDER BY instrument_id", params
            ).fetchall()
            return [Instrument.from_json(r["payload_json"]) for r in rows]

    def get_mappings(self, instrument_id: str) -> List[ProviderInstrumentMapping]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM provider_mappings WHERE instrument_id = ? ORDER BY is_primary DESC, mapping_id",
                (instrument_id,),
            ).fetchall()
            return [self._row_to_mapping(r) for r in rows]

    def resolve_provider(
        self,
        provider: str,
        provider_symbol: str,
        provider_exchange: Optional[str] = None,
        provider_feed: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> Optional[Instrument]:
        check_ts = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        clauses = ["LOWER(pm.provider) = ?", "pm.provider_symbol = ?"]
        params: list = [provider.strip().lower(), provider_symbol]
        if provider_exchange is not None:
            clauses.append("UPPER(pm.provider_exchange) = ?")
            params.append(provider_exchange.strip().upper())
        if provider_feed is not None:
            clauses.append("LOWER(pm.provider_feed) = ?")
            params.append(provider_feed.strip().lower())

        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT pm.valid_from, pm.valid_until, i.instrument_id, i.payload_json
                FROM provider_mappings pm
                JOIN instruments i ON i.instrument_id = pm.instrument_id
                WHERE {' AND '.join(clauses)}
                """,
                tuple(params),
            ).fetchall()

            matched: dict = {}
            for r in rows:
                vf = _parse_opt_dt(r["valid_from"])
                vu = _parse_opt_dt(r["valid_until"])
                if (vf is None or vf <= check_ts) and (vu is None or check_ts < vu):
                    matched[r["instrument_id"]] = r["payload_json"]
            if not matched:
                return None
            if len(matched) > 1:
                raise RegistryConflictError(
                    f"Ambiguous active provider lookup at {check_ts.isoformat()} for "
                    f"({provider}, {provider_symbol}, {provider_exchange}, {provider_feed})"
                )
            return Instrument.from_json(next(iter(matched.values())))

    def get_spec_history(self, instrument_id: str) -> List[InstrumentSpecVersion]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM instrument_spec_versions
                WHERE instrument_id = ?
                ORDER BY CASE WHEN effective_from IS NULL THEN 0 ELSE 1 END, effective_from ASC, version_id ASC
                """,
                (instrument_id,),
            ).fetchall()
            return [
                InstrumentSpecVersion(
                    version_id=r["version_id"],
                    instrument_id=r["instrument_id"],
                    effective_from=_parse_opt_dt(r["effective_from"]),
                    effective_to=_parse_opt_dt(r["effective_to"]),
                    spec_hash=r["spec_hash"],
                    specification=json.loads(r["spec_json"]),
                    recorded_at=datetime.fromisoformat(r["recorded_at"]),
                )
                for r in rows
            ]

    @staticmethod
    def _row_to_mapping(r: sqlite3.Row) -> ProviderInstrumentMapping:
        return ProviderInstrumentMapping.from_dict(
            {
                "mapping_id": r["mapping_id"],
                "instrument_id": r["instrument_id"],
                "provider": r["provider"],
                "provider_instrument_id": r["provider_instrument_id"],
                "provider_symbol": r["provider_symbol"],
                "provider_exchange": r["provider_exchange"] or None,
                "provider_feed": r["provider_feed"] or None,
                "valid_from": r["valid_from"],
                "valid_until": r["valid_until"],
                "last_verified_at": r["last_verified_at"],
                "is_primary": bool(r["is_primary"]),
            }
        )
