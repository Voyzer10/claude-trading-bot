"""Alpaca Market Data (DATA ONLY) adapter for US Stocks bars.

Safety:
- Only HTTPS GET to data.alpaca.markets, only /v2/stocks/.../bars paths. Trading hosts (api.alpaca.markets,
  paper-api.alpaca.markets) and any other method or path are refused before a request is built: there is no order path.
- Credentials are a SEPARATE V6 data-only key supplied by the owner, read from a V6 credential file (default
  /etc/trader-v6/alpaca-data.json, mode 0600, owner trader-v6). V4's file (/etc/trader/trader.env) and V4's variable
  names are never read. Secrets are never logged or returned (repr is masked).
- The HTTP transport is injectable; tests use recorded/synthetic fixtures and never touch the network.
"""
from __future__ import annotations

import json
import os
import stat
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

DATA_HOST = "data.alpaca.markets"
FORBIDDEN_HOSTS = ("api.alpaca.markets", "paper-api.alpaca.markets", "broker-api.alpaca.markets")
DEFAULT_CREDENTIAL_FILE = "/etc/trader-v6/alpaca-data.json"
TIMEFRAMES = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour"}


class AlpacaDataError(RuntimeError):
    pass


class CredentialError(AlpacaDataError):
    pass


@dataclass(frozen=True)
class DataCredential:
    key_id: str
    secret: str
    source: str

    def __repr__(self) -> str:  # never print secrets
        return "DataCredential(key_id=%s…, source=%s)" % (self.key_id[:4], self.source)

    def headers(self) -> Dict[str, str]:
        return {"APCA-API-KEY-ID": self.key_id, "APCA-API-SECRET-KEY": self.secret}


def load_credential(path: str = DEFAULT_CREDENTIAL_FILE) -> Optional[DataCredential]:
    """The V6 data-only credential, or None if the owner has not supplied it. Refuses V4 locations and files readable
    by other users."""
    real = os.path.realpath(path)
    if real.startswith("/etc/trader/") or os.path.basename(real) == "trader.env" or "/opt/trader" in real:
        raise CredentialError("refusing %s: V6 never reads V4 secrets" % path)
    if not os.path.exists(real):
        return None
    mode = os.stat(real).st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CredentialError("%s must not be readable by group/other (chmod 600)" % path)
    with open(real, encoding="utf-8") as fh:
        d = json.load(fh)
    if d.get("purpose") != "v6-data-only":
        raise CredentialError("%s must declare purpose 'v6-data-only'" % path)
    k, s = d.get("key_id"), d.get("secret")
    if not (isinstance(k, str) and k and isinstance(s, str) and s):
        raise CredentialError("%s needs key_id and secret" % path)
    return DataCredential(k, s, path)


def check_request(method: str, url: str) -> None:
    """The only requests this adapter may make. Raises before anything is sent."""
    if method != "GET":
        raise AlpacaDataError("only GET is allowed (got %s): the V6 adapter cannot place orders" % method)
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname in FORBIDDEN_HOSTS or u.hostname != DATA_HOST:
        raise AlpacaDataError("host %r is not the Alpaca market-data host" % u.hostname)
    if not (u.path.startswith("/v2/stocks/") and u.path.endswith("/bars")) and u.path != "/v2/stocks/bars":
        raise AlpacaDataError("path %r is not a bars endpoint" % u.path)


Transport = Callable[[str, str, Dict[str, str]], Dict]


def urllib_transport(method: str, url: str, headers: Dict[str, str]) -> Dict:
    check_request(method, url)
    req = urllib.request.Request(url, headers=dict(headers, Accept="application/json"), method=method)
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - host checked above
        return json.loads(r.read().decode("utf-8"))


@dataclass(frozen=True)
class Bar:
    symbol: str
    start: datetime      # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_bars(symbol: str, payload: Dict) -> List[Bar]:
    rows = payload.get("bars")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise AlpacaDataError("bars must be a list")
    out = []
    for b in rows:
        try:
            t = datetime.fromisoformat(b["t"].replace("Z", "+00:00"))
            out.append(Bar(symbol, t.astimezone(timezone.utc), float(b["o"]), float(b["h"]), float(b["l"]),
                           float(b["c"]), float(b["v"])))
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise AlpacaDataError("malformed bar for %s: %r (%s)" % (symbol, b, e)) from e
    return out


class AlpacaBars:
    def __init__(self, credential: DataCredential, feed: str, transport: Transport = urllib_transport):
        if feed not in ("iex", "sip"):
            raise AlpacaDataError("feed must be iex or sip (owner decision)")
        if not isinstance(credential, DataCredential):
            raise CredentialError("a V6 DataCredential is required")
        self.cred, self.feed, self.transport = credential, feed, transport

    def url(self, symbol: str, timeframe: str, start: datetime, end: datetime, page_token: Optional[str] = None) -> str:
        if timeframe not in TIMEFRAMES:
            raise AlpacaDataError("unsupported timeframe %s" % timeframe)
        q = {"timeframe": TIMEFRAMES[timeframe], "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
             "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "feed": self.feed,
             "adjustment": "raw", "limit": "10000", "sort": "asc"}
        if page_token:
            q["page_token"] = page_token
        return "https://%s/v2/stocks/%s/bars?%s" % (DATA_HOST, urllib.parse.quote(symbol), urllib.parse.urlencode(q))

    def fetch(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> List[Bar]:
        out, token = [], None
        for _ in range(50):
            url = self.url(symbol, timeframe, start, end, token)
            check_request("GET", url)
            payload = self.transport("GET", url, self.cred.headers())
            out.extend(parse_bars(symbol, payload))
            token = payload.get("next_page_token")
            if not token:
                return out
        raise AlpacaDataError("too many pages for %s" % symbol)
