"""Read-only historical coverage and feed entitlement preflight for Alpaca US assets."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from ..instruments import AssetClass, InstrumentRegistry, Market
from .config import NY_TZ, UTC_TZ, USCalendar
from .exceptions import AlpacaAdapterError, AlpacaAuthError, AlpacaPaginationIncompleteError, AlpacaSubscriptionError
from .historical import AlpacaHistoricalOptions, AlpacaHistoricalStocks, expected_us_session_timestamps


class AlpacaCoveragePreflight:
    """Read-only coverage and subscription entitlement preflight for US equities, indices, and options."""

    def __init__(
        self,
        *,
        stocks_client: AlpacaHistoricalStocks,
        options_client: AlpacaHistoricalOptions,
        registry: InstrumentRegistry,
        calendar: Optional[USCalendar] = None,
    ) -> None:
        self.stocks = stocks_client
        self.options = options_client
        self.registry = registry
        self.calendar = calendar or USCalendar()

    def _safe_end(self, end: Optional[datetime], basic_plan_delay_minutes: int = 16) -> datetime:
        now_utc = datetime.now(UTC_TZ)
        limit_end = now_utc - timedelta(minutes=basic_plan_delay_minutes)
        if end is None:
            return limit_end
        e_utc = end.astimezone(UTC_TZ) if end.tzinfo else end.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        return min(e_utc, limit_end) if e_utc > limit_end else e_utc

    def check_equities(
        self,
        symbols: Sequence[str] = ("AAPL", "MSFT", "NVDA", "SPY", "QQQ"),
        *,
        start: datetime,
        end: Optional[datetime] = None,
        feed: str = "iex",
        adjustment: str = "raw",
        timeframes: Sequence[str] = ("1Min", "5Min", "15Min", "1Hour"),
    ) -> List[Dict[str, Any]]:
        e_utc = self._safe_end(end)
        s_utc = start.astimezone(UTC_TZ) if start.tzinfo else start.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        cal_ok = self.calendar.is_verified_for_range(s_utc.astimezone(NY_TZ).date(), e_utc.astimezone(NY_TZ).date())

        report: List[Dict[str, Any]] = []
        for sym in symbols:
            s_u = sym.strip().upper()
            inst = self.registry.resolve_provider_symbol("alpaca", s_u)
            if inst is None:
                inst = next((i for i in self.registry.list_by_market(Market.US) if i.canonical_symbol == s_u), None)
            insts = [inst] if inst is not None else []
            entry: Dict[str, Any] = {
                "symbol": s_u,
                "instrument_id": insts[0].instrument_id if insts else None,
                "provider_available": bool(insts),
                "contract_status": insts[0].instrument_status.value if insts else "UNAVAILABLE",
                "feed_requested": feed,
                "feed_accepted": None,
                "adjustment": adjustment,
                "calendar_verified": cal_ok,
                "timeframes": {},
                "earliest": None,
                "latest": None,
                "status": "EMPTY_RESPONSE",
            }
            if not insts:
                entry["status"] = "UNSUPPORTED"
                report.append(entry)
                continue

            has_data = False
            all_covered = True
            sub_err = False
            auth_err = False
            part_err = False
            pag_inc = False
            total_missing = 0
            late_close = bool((insts[0].metadata or {}).get("options_late_close", False))
            for tf in timeframes:
                try:
                    res = self.stocks.fetch_bars([s_u], timeframe=tf, start=s_utc, end=e_utc, feed=feed, adjustment=adjustment)
                    bars = res.bars_by_symbol.get(s_u, [])
                    e0 = bars[0].ts_utc.isoformat() if bars else None
                    e1 = bars[-1].ts_utc.isoformat() if bars else None
                    expected_ts = expected_us_session_timestamps(
                        self.calendar, tf, s_utc, e_utc, options_late_close=late_close, require_verified=cal_ok
                    )
                    present_ts = {b.ts_utc for b in bars}
                    missing_expected = [ts for ts in expected_ts if ts not in present_ts]
                    tf_missing = len(missing_expected)
                    total_missing += tf_missing
                    tf_covered = res.pagination_complete and len(expected_ts) > 0 and tf_missing == 0

                    if not res.pagination_complete:
                        pag_inc = True
                        tf_status = "PAGINATION_INCOMPLETE"
                        all_covered = False
                    elif not cal_ok:
                        tf_status = "UNVERIFIED_CALENDAR"
                        all_covered = False
                    elif not bars:
                        tf_status = "EMPTY_RESPONSE"
                        all_covered = False
                    elif tf_covered:
                        tf_status = "VERIFIED_WITH_DATA"
                    else:
                        tf_status = "PARTIAL_DATA"
                        all_covered = False

                    entry["timeframes"][tf] = {
                        "bar_count": len(bars),
                        "expected_count": len(expected_ts),
                        "range_covered": tf_covered,
                        "earliest": e0,
                        "latest": e1,
                        "pages_fetched": res.pages_fetched,
                        "pagination_complete": res.pagination_complete,
                        "missing_in_session": tf_missing,
                        "status": tf_status,
                    }
                    if bars:
                        has_data = True
                        entry["feed_accepted"] = feed
                        entry["earliest"] = min(entry["earliest"], e0) if entry["earliest"] else e0
                        entry["latest"] = max(entry["latest"], e1) if entry["latest"] else e1
                except AlpacaPaginationIncompleteError as e:
                    pag_inc = True
                    all_covered = False
                    entry["timeframes"][tf] = {"status": "PAGINATION_INCOMPLETE", "error": str(e)}
                except AlpacaSubscriptionError as e:
                    sub_err = True
                    all_covered = False
                    entry["timeframes"][tf] = {"status": "BLOCKED_BY_SUBSCRIPTION", "error": str(e)}
                except AlpacaAuthError as e:
                    auth_err = True
                    all_covered = False
                    entry["timeframes"][tf] = {"status": "BLOCKED_BY_AUTH", "error": str(e)}
                except AlpacaAdapterError as e:
                    part_err = True
                    all_covered = False
                    entry["timeframes"][tf] = {"status": "PARTIAL_DATA", "error": str(e)}

            entry["data_returned"] = has_data
            entry["range_covered"] = has_data and all_covered and cal_ok and not pag_inc
            entry["missing_count"] = total_missing

            if auth_err:
                entry["status"] = "BLOCKED_BY_AUTH"
            elif sub_err:
                entry["status"] = "BLOCKED_BY_SUBSCRIPTION"
            elif pag_inc:
                entry["status"] = "PAGINATION_INCOMPLETE"
            elif part_err:
                entry["status"] = "PARTIAL_DATA"
            elif not cal_ok:
                entry["status"] = "UNVERIFIED_CALENDAR"
            elif not has_data:
                entry["status"] = "EMPTY_RESPONSE"
            elif all_covered:
                entry["status"] = "VERIFIED_WITH_DATA"
            else:
                entry["status"] = "PARTIAL_DATA"
            report.append(entry)
        return report

    def check_options(
        self,
        occ_symbols: Sequence[str],
        *,
        start: datetime,
        end: Optional[datetime] = None,
        feed: str = "indicative",
    ) -> List[Dict[str, Any]]:
        e_utc = self._safe_end(end)
        s_utc = start.astimezone(UTC_TZ) if start.tzinfo else start.replace(tzinfo=NY_TZ).astimezone(UTC_TZ)
        report: List[Dict[str, Any]] = []
        for sym in occ_symbols:
            s_u = sym.strip().upper()
            inst = self.registry.resolve_provider_symbol("alpaca", s_u)
            if inst is None:
                inst = next((i for i in self.registry.list_by_market(Market.US) if i.canonical_symbol == s_u and i.asset_class == AssetClass.OPTION), None)
            insts = [inst] if (inst is not None and inst.asset_class == AssetClass.OPTION) else []
            entry: Dict[str, Any] = {
                "symbol": s_u,
                "instrument_id": insts[0].instrument_id if insts else None,
                "contract_status": insts[0].instrument_status.value if insts else "UNAVAILABLE",
                "feed_requested": feed,
                "feed_accepted": None,
                "bars": {},
                "quotes": {},
                "trades": {},
                "status": "EMPTY_RESPONSE",
            }
            if not insts:
                entry["status"] = "UNSUPPORTED"
                report.append(entry)
                continue
            try:
                bars_map, b_pages = self.options.fetch_bars([s_u], timeframe="5Min", start=s_utc, end=e_utc, feed=feed)
                b_stats = dict(self.options.last_fetch_stats)
                quotes_map, q_pages = self.options.fetch_quotes([s_u], start=s_utc, end=e_utc, feed=feed)
                q_stats = dict(self.options.last_fetch_stats)
                trades_map, t_pages = self.options.fetch_trades([s_u], start=s_utc, end=e_utc, feed=feed)
                t_stats = dict(self.options.last_fetch_stats)

                b_lst, q_lst, t_lst = bars_map.get(s_u, []), quotes_map.get(s_u, []), trades_map.get(s_u, [])
                pag_ok = (
                    b_stats.get("pagination_complete", True)
                    and q_stats.get("pagination_complete", True)
                    and t_stats.get("pagination_complete", True)
                )
                pre_feb = (
                    b_stats.get("unavailable_pre_feb_2024", False)
                    or q_stats.get("unavailable_pre_feb_2024", False)
                    or t_stats.get("unavailable_pre_feb_2024", False)
                )
                entry["bars"] = {
                    "count": len(b_lst), "pages": b_pages,
                    "pagination_complete": b_stats.get("pagination_complete", True),
                    "earliest": b_lst[0].ts_utc.isoformat() if b_lst else None,
                    "latest": b_lst[-1].ts_utc.isoformat() if b_lst else None,
                }
                entry["quotes"] = {
                    "count": len(q_lst), "pages": q_pages,
                    "pagination_complete": q_stats.get("pagination_complete", True),
                    "earliest": q_lst[0].ts_utc.isoformat() if q_lst else None,
                    "latest": q_lst[-1].ts_utc.isoformat() if q_lst else None,
                }
                entry["trades"] = {
                    "count": len(t_lst), "pages": t_pages,
                    "pagination_complete": t_stats.get("pagination_complete", True),
                    "earliest": t_lst[0].ts_utc.isoformat() if t_lst else None,
                    "latest": t_lst[-1].ts_utc.isoformat() if t_lst else None,
                }
                entry["range_covered"] = False
                entry["unavailable_pre_feb_2024"] = pre_feb
                if not pag_ok:
                    entry["status"] = "PAGINATION_INCOMPLETE"
                elif b_lst or q_lst or t_lst:
                    entry["feed_accepted"] = feed
                    # Sparse option bars/quotes cannot prove full-range no-trade vs missing-data completeness
                    entry["status"] = "UNKNOWN"
                else:
                    entry["status"] = "EMPTY_RESPONSE"
            except AlpacaPaginationIncompleteError as e:
                entry["status"] = "PAGINATION_INCOMPLETE"
                entry["error"] = str(e)
            except AlpacaSubscriptionError as e:
                entry["status"] = "BLOCKED_BY_SUBSCRIPTION"
                entry["error"] = str(e)
            except AlpacaAuthError as e:
                entry["status"] = "BLOCKED_BY_AUTH"
                entry["error"] = str(e)
            except AlpacaAdapterError as e:
                entry["status"] = "PARTIAL_DATA"
                entry["error"] = str(e)
            report.append(entry)
        return report
