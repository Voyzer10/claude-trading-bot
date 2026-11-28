"""Safe, read-only multi-market provider preflight runner (`python -m ml_data.preflight`)."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Sequence

from .crypto import (
    COINDCX_API_BASE,
    CoinDCXDiscovery,
    CoinDCXHistoricalClient,
    CryptoCoveragePreflight,
    PublicCryptoHTTPClient,
    inspect_coindcx_credentials,
)
from .futures import inspect_databento_credentials
from .us import inspect_alpaca_credentials


def _inspect_kite_credentials() -> Dict[str, str]:
    try:
        import kite as K
        k, s = K.keys()
        sess = K.load_session()
        key_st = "PRESENT" if (k and s) else ("INVALID" if (k or s) else "ABSENT")
        sess_st = "PRESENT" if (sess and sess.get("access_token")) else "ABSENT"
        return {"KITE_API_KEY/SECRET": key_st, "KITE_SESSION": sess_st}
    except Exception:
        return {"KITE_API_KEY/SECRET": "INVALID", "KITE_SESSION": "INVALID"}


def run_kite_preflight() -> Dict[str, Any]:
    creds = _inspect_kite_credentials()
    if creds.get("KITE_SESSION") != "PRESENT":
        return {"provider": "kite", "credentials": creds, "status": "BLOCKED_BY_AUTH"}
    try:
        from .india import KiteClientWrapper
        c = KiteClientWrapper(max_retries=1)
        nse_csv = c.fetch_instruments_csv("NSE")
        return {"provider": "kite", "credentials": creds, "nse_bytes": len(nse_csv), "status": "VERIFIED_WITH_DATA"}
    except Exception as e:
        return {"provider": "kite", "credentials": creds, "status": "BLOCKED_BY_AUTH", "error": str(e)[:200]}


def run_alpaca_preflight() -> Dict[str, Any]:
    creds = inspect_alpaca_credentials()
    if not any(v == "PRESENT" for v in creds.values()):
        return {"provider": "alpaca", "credentials": creds, "status": "BLOCKED_BY_AUTH"}
    try:
        from .us import AlpacaDataClient
        c = AlpacaDataClient(max_retries=1)
        resp = c.request("trading", "/v2/assets", params={"asset_class": "us_equity", "status": "active"})
        cnt = len(resp.body) if isinstance(resp.body, list) else 0
        end = datetime.now(timezone.utc) - timedelta(minutes=20)
        start = end - timedelta(days=3)
        b_resp = c.request(
            "data",
            "/v2/stocks/bars",
            params={
                "symbols": "AAPL",
                "timeframe": "1Hour",
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": end.isoformat().replace("+00:00", "Z"),
                "feed": "iex",
                "adjustment": "raw",
                "limit": 5,
            },
        )
        aapl_bars = len(((b_resp.body or {}).get("bars") or {}).get("AAPL") or [])
        return {
            "provider": "alpaca",
            "credentials": creds,
            "active_assets_count": cnt,
            "aapl_1h_iex_bars": aapl_bars,
            "status": "VERIFIED_WITH_DATA" if aapl_bars > 0 else "EMPTY_RESPONSE",
        }
    except Exception as e:
        return {"provider": "alpaca", "credentials": creds, "status": "UNAVAILABLE", "error": str(e)[:200]}


def run_coindcx_preflight(*, client: Optional[PublicCryptoHTTPClient] = None) -> Dict[str, Any]:
    creds = inspect_coindcx_credentials()
    http = client or PublicCryptoHTTPClient(max_retries=1)
    out: Dict[str, Any] = {"provider": "coindcx", "credentials": creds}
    try:
        disc = CoinDCXDiscovery(client=http)
        spot_rep = disc.discover_spot(universe=("BTC", "ETH"), dry_run=True)
        fut_rep = disc.discover_futures(margin_currencies=("USDT", "INR"), universe=("BTC", "ETH"), dry_run=True)

        hist = CoinDCXHistoricalClient(client=http)
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=2)
        spot_bars = []
        if spot_rep.spot_instruments:
            pair = spot_rep.spot_instruments[0].provider_symbol
            spot_bars = hist.fetch_spot_candles(pair, interval="15m", start=start, end=end, limit=10)
        fut_bars = []
        if fut_rep.perpetual_instruments:
            fpair = fut_rep.perpetual_instruments[0].provider_symbol
            fut_bars = hist.fetch_futures_candles(fpair, interval="5m", start=start, end=end)

        out.update({
            "spot_btc_eth_count": len(spot_rep.spot_instruments),
            "perpetual_btc_eth_count": len(fut_rep.perpetual_instruments),
            "dated_futures_count": len(fut_rep.dated_futures_instruments),
            "dated_futures_status": fut_rep.dated_futures_status,
            "spot_sample_candles": len(spot_bars),
            "futures_sample_candles": len(fut_bars),
            "historical_funding_status": "UNSUPPORTED",
            "historical_oi_status": "UNSUPPORTED",
            "status": "VERIFIED_WITH_DATA" if (spot_bars or fut_bars) else "PARTIAL_DATA",
        })
        return out
    except Exception as e:
        out["status"] = "UNAVAILABLE"
        out["error"] = str(e)[:200]
        return out


def run_all_preflights(*, live: bool = False) -> Dict[str, Any]:
    if not live:
        return {
            "mode": "offline_credential_inspection_only",
            "kite": {"credentials": _inspect_kite_credentials(), "status": "UNVERIFIED"},
            "alpaca": {"credentials": inspect_alpaca_credentials(), "status": "UNVERIFIED"},
            "coindcx": {"credentials": inspect_coindcx_credentials(), "status": "UNVERIFIED"},
            "databento": {"credentials": inspect_databento_credentials(), "status": "DEFERRED_BY_USER"},
        }
    return {
        "mode": "live_read_only_preflight",
        "kite": run_kite_preflight(),
        "alpaca": run_alpaca_preflight(),
        "coindcx": run_coindcx_preflight(),
        "databento": {"credentials": inspect_databento_credentials(), "status": "DEFERRED_BY_USER"},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Safe read-only multi-market preflight.")
    p.add_argument("--live", action="store_true", help="Execute small read-only live API checks.")
    args = p.parse_args(argv)
    print(json.dumps(run_all_preflights(live=args.live), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
