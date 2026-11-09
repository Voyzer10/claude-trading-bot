#!/usr/bin/env python3
"""Zerodha (kite.py, kite_ticker.py): data only, never an order. Offline: no request leaves the machine.

    python tests/test_kite.py
"""
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAILS = []


def check(name, ok, extra=""):
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, (": %s" % (extra,)) if not ok else ""))
    if not ok:
        FAILS.append(name)


INSTR = {
    "NSE": "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,"
           "instrument_type,segment,exchange\n"
           "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
           "256265,1001,NIFTY 50,NIFTY 50,0,,0,0,0,EQ,INDICES,NSE\n"
           "260105,1016,NIFTY BANK,NIFTY BANK,0,,0,0,0,EQ,INDICES,NSE\n"
           "270000,2000,INDIA VIX,INDIA VIX,0,,0,0,0,EQ,INDICES,NSE\n"
           "270001,2001,NIFTY ENERGY,NIFTY ENERGY,0,,0,0,0,EQ,INDICES,NSE\n"
           "270002,2002,NIFTY FIN SERVICE,NIFTY FIN SERVICE,0,,0,0,0,EQ,INDICES,NSE\n"
           "270003,2003,NIFTY FMCG,NIFTY FMCG,0,,0,0,0,EQ,INDICES,NSE\n"
           "270004,2004,NIFTY INFRA,NIFTY INFRA,0,,0,0,0,EQ,INDICES,NSE\n"
           "270005,2005,NIFTY REALTY,NIFTY REALTY,0,,0,0,0,EQ,INDICES,NSE\n"
           "270006,2006,NIFTY AUTO,NIFTY AUTO,0,,0,0,0,EQ,INDICES,NSE\n"
           "270007,2007,NIFTY IT,NIFTY IT,0,,0,0,0,EQ,INDICES,NSE\n"
           "270008,2008,NIFTY METAL,NIFTY METAL,0,,0,0,0,EQ,INDICES,NSE\n"
           "270009,2009,NIFTY PHARMA,NIFTY PHARMA,0,,0,0,0,EQ,INDICES,NSE\n",
    "NFO": "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,"
           "instrument_type,segment,exchange\n"
           "12345602,48225,NIFTY25N1725500CE,NIFTY,0,2026-11-17,25500,0.05,75,CE,NFO-OPT,NFO\n"
           "12345603,48226,NIFTY25N2425500CE,NIFTY,0,2026-11-24,25500,0.05,75,CE,NFO-OPT,NFO\n"
           "12345610,48230,NIFTY26NOVFUT,NIFTY,0,2026-11-24,0,0.1,75,FUT,NFO-FUT,NFO\n"
           "22345602,58225,RELIANCE26NOV1412.5CE,RELIANCE,0,2026-11-24,1412.5,0.05,500,CE,NFO-OPT,NFO\n"
           "22345603,58226,RELIANCE26NOV1400PE,RELIANCE,0,2026-11-24,1400,0.05,500,PE,NFO-OPT,NFO\n"
           "22345610,58230,RELIANCE26NOVFUT,RELIANCE,0,2026-11-24,0,0.1,500,FUT,NFO-FUT,NFO\n",
}


if __name__ == "__main__":
    tmp, old = tempfile.mkdtemp(), os.getcwd()
    os.chdir(tmp)
    sent = []

    def no_network(req, *a, **k):
        sent.append(req.full_url if hasattr(req, "full_url") else req)
        raise AssertionError("network call during an offline test: %s" % sent[-1])
    urllib.request.urlopen = no_network
    os.environ["KITE_API_KEY"] = "testkey123"
    os.environ["KITE_API_SECRET"] = "testsecret456"
    try:
        import kite as K

        # ---- 1. orders can not leave this bot
        bad = [("POST", "/orders/regular"), ("POST", "/orders/amo"), ("PUT", "/orders/regular/123"),
               ("DELETE", "/orders/regular/123"), ("GET", "/orders"), ("POST", "/gtt/triggers"),
               ("PUT", "/portfolio/positions"), ("GET", "/portfolio/positions"), ("POST", "/mf/orders"),
               ("GET", "/user/margins"), ("POST", "/quote"), ("GET", "/quote/../orders"),
               ("GET", "/instruments/historical/1/minute/../../orders")]
        blocked = 0
        for m, path in bad:
            try:
                K._call(m, path)
            except K.KiteBlocked:
                blocked += 1
            except Exception:
                pass
        check("1. every order / position / GTT / margin request is refused before it is sent (%d of %d)"
              % (blocked, len(bad)), blocked == len(bad) and not sent, sent)
        words = " ".join(rx for _, rx in K.ALLOWED).lower()
        check("   the allow list has no order, GTT, portfolio or MF endpoint",
              not any(w in words for w in ("order", "gtt", "portfolio", "mf", "margin")), K.ALLOWED)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = "".join(open(os.path.join(here, f), encoding="utf-8").read()
                      for f in ("kite.py", "kite_ticker.py", "api/_kite.py"))
        check("   no order call anywhere in the Zerodha code (place_order, /orders, kiteconnect)",
              not any(w in src for w in ("place_order", "modify_order", "cancel_order", '"/orders', "kiteconnect")))

        # ---- 2. the daily login
        got = {}

        def fake_call(method, path, params=None, data=None, auth=True, **kw):
            if not K._allowed(method, path):
                raise K.KiteBlocked(path)
            got.update(method=method, path=path, data=data, auth=auth)
            return {"access_token": "tok_abc", "user_id": "AB1234"}
        real_call = K._call
        K._call = fake_call
        st = K.exchange("reqtoken987")
        K._call = real_call
        check("2. login: request_token + sha256(key + token + secret) -> today's session",
              got["path"] == "/session/token" and got["data"]["checksum"] == hashlib.sha256(
                  b"testkey123reqtoken987testsecret456").hexdigest() and st["connected"] and st["user"] == "AB1234", got)
        check("   the status the dashboard sees has no key, secret or token",
              not any(x in json.dumps(st) for x in ("testkey123", "testsecret456", "tok_abc")), st)
        mode = oct(os.stat(K.SESSION_FILE).st_mode & 0o777)
        check("   the session file is private (600)", mode == "0o600", mode)
        try:
            K.exchange("bad token; rm -rf")
            check("   a malformed request_token is refused", False)
        except K.KiteError:
            check("   a malformed request_token is refused", True)
        ist = K.IST
        e1 = K._expiry_after(datetime(2026, 11, 10, 10, 0, tzinfo=ist))
        e2 = K._expiry_after(datetime(2026, 11, 10, 5, 0, tzinfo=ist))
        check("   tokens expire at 6:00 IST: a 10:00 login lasts to tomorrow 6:00, a 5:00 login to today 6:00",
              e1 == datetime(2026, 11, 11, 6, 0, tzinfo=ist) and e2 == datetime(2026, 11, 10, 6, 0, tzinfo=ist), (e1, e2))

        # ---- 3. paper keys -> Kite instruments
        os.makedirs(K.INSTR_DIR, exist_ok=True)
        today = datetime.now(K.IST).date().isoformat()
        for ex, text in INSTR.items():
            with open(os.path.join(K.INSTR_DIR, "%s-%s.csv" % (ex, today)), "w") as fh:
                fh.write(text)
        r = {k: K.resolve(k) for k in ("NSE:RELIANCE", "NSE:NIFTY50", "NSE:BANKNIFTY", "NFO:NIFTY-20261117-25500-CE",
                                       "NFO:NIFTY-FUT-20261124", "NFO:RELIANCE-20261124-1412.5-CE",
                                       "NFO:RELIANCE-FUT-20261124")}
        check("3. resolve: stock, indices, index option (right expiry), future, stock option (half strike)",
              r["NSE:RELIANCE"]["token"] == 738561 and r["NSE:NIFTY50"]["kite"] == "NSE:NIFTY 50"
              and r["NSE:BANKNIFTY"]["token"] == 260105 and r["NFO:NIFTY-20261117-25500-CE"]["token"] == 12345602
              and r["NFO:NIFTY-FUT-20261124"]["tradingsymbol"] == "NIFTY26NOVFUT"
              and r["NFO:RELIANCE-20261124-1412.5-CE"]["lot"] == 500, r)
        try:
            K.resolve("NFO:NIFTY-20261117-25550-CE")
            check("   a strike that does not exist is an error, not a guess", False)
        except K.KiteError:
            check("   a strike that does not exist is an error, not a guess", True)
        ch = K.fno_chain("RELIANCE")
        check("   stock F&O chain: RELIANCE has CE / PE / FUT with lot 500",
              {c["type"] for c in ch} == {"CE", "PE", "FUT"} and all(c["lot"] == 500 for c in ch), ch)
        check("   paper names round-trip (RELIANCE-20261124-1412.5-CE)",
              K.paper_name([c for c in ch if c["type"] == "CE"][0], "RELIANCE") == "RELIANCE-20261124-1412.5-CE")

        import kite_ticker as T
        w = T.wanted()
        ok_keys = {k for k, _ in K.WATCH_INDICES} - {"NSE:NIFTYPSE"}
        check("   the index watch list (Bank Nifty + the CNX sector indices) is streamed: %d of %d resolve"
              % (len(set(w.values()) & ok_keys), len(ok_keys)), ok_keys <= set(w.values()), sorted(w.values()))
        check("   an index Kite does not list (PSE missing from this fake list) is reported, not silent",
              T.MISSING == ["NSE:NIFTYPSE"], T.MISSING)

        # ---- 4. WebSocket packets
        def pk(*ints, fmt=None):
            return struct.pack(fmt or (">" + "i" * len(ints)), *ints)
        ltp = struct.pack(">I", 738561) + pk(298050)
        idx = struct.pack(">I", 256265) + pk(2550010, 2560000, 2540000, 2545000, 2541000, 9010) + struct.pack(">I", 1794000000)
        full = (struct.pack(">I", 12345602) + struct.pack(">iiiIIIiiii", 12345, 75, 12000, 900000, 1, 1, 11000, 13000,
                                                           10500, 11500) + struct.pack(">IIIII", 1794000000, 456000, 0, 0, 1794000001)
                + b"\x00" * 120)
        msg = struct.pack(">H", 3) + b"".join(struct.pack(">H", len(p)) + p for p in (ltp, idx, full))
        import kite_ticker as T
        out = T.parse_binary(msg)
        check("4. ticker packets: LTP, index (with time) and full quote decode (paise -> rupees)",
              len(out) == 3 and out[0]["ltp"] == 2980.5 and out[1]["ltp"] == 25500.1 and out[1]["close"] == 25410.0
              and out[1]["t"] == 1794000000 and out[2]["ltp"] == 123.45 and out[2]["high"] == 130.0
              and out[2]["oi"] == 456000 and out[2]["t"] == 1794000001, out)
        check("   a heartbeat (1 byte) is nothing", T.parse_binary(b"\x00") == [])

        # ---- 5. paper.py prices from the tick stream when connected
        with open(K.TICKS_FILE, "w") as fh:
            json.dump({"written": time.time(), "ticks": {"NSE:RELIANCE": {"ltp": 2980.5, "t": time.time()},
                                                         "NFO:NIFTY-20261117-25500-CE": {"ltp": 123.45, "t": time.time()}}}, fh)
        import paper as P
        p1 = P.fetch_price("NSE", "RELIANCE")
        p2 = P.fetch_price("NFO", "NIFTY-20261117-25500-CE")
        check("5. paper prices NSE and F&O from the live Zerodha ticks", p1[0] == 2980.5 and p2[0] == 123.45, (p1, p2))
        check("   lot size from the exchange's own list (RELIANCE option: 500)",
              P.lot_of("NFO", "RELIANCE-20261124-1412.5-CE") == 500)
        with open(K.TICKS_FILE, "w") as fh:
            json.dump({"written": time.time() - 60, "ticks": {"NSE:RELIANCE": {"ltp": 1.0}}}, fh)
        check("   a stale tick file (60 s old) is not used", K.tick_price("NSE:RELIANCE") is None)
        K.forget_session()
        check("   not connected: no Kite at all (paper falls back to Yahoo / the model)",
              P.kite_mod() is None and P.kite_price("NSE", "RELIANCE") is None)
        check("   and nothing was sent over the network in this whole test", not sent, sent)
    finally:
        os.chdir(old)
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%s" % ("all checks passed" if not FAILS else "%d FAILED: %s" % (len(FAILS), ", ".join(FAILS))))
    sys.exit(1 if FAILS else 0)
