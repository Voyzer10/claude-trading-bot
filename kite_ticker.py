#!/usr/bin/env python3
"""
kite_ticker.py - live Indian market ticks from Zerodha's WebSocket, written every second to trader/live/ticks.json
for the dashboard (prices changing every second) and paper.py (stops / targets on the freshest price).

Read only: the WebSocket only streams prices. Nothing here can place an order.

Subscribes to: Nifty 50, Bank Nifty, India VIX, every open NSE / BSE / NFO paper position, and the symbols in
trader/live/kite_watch.json (written by the F&O agent). The list is re-read every 10 seconds.
Needs today's Kite login (dashboard: Control > Connect Zerodha); without it, it waits and retries.

Service: deploy/trader-ticker.service.   By hand:  python kite_ticker.py
"""
import json
import os
import struct
import sys
import threading
import time
from datetime import datetime, timezone

import kite as K

LEDGER = os.path.join("trader", "paper", "ledger.json")
WATCH = os.path.join("trader", "live", "kite_watch.json")
ALWAYS = ["NSE:NIFTY50", "NSE:BANKNIFTY", "NSE:INDIAVIX"]
WS = "wss://ws.kite.trade?api_key=%s&access_token=%s"


def log(msg):
    print("%s %s" % (datetime.now(K.IST).strftime("%H:%M:%S"), msg), flush=True)


# ------------------------------------------------------------------ the binary packets

def _div(token):
    seg = token & 0xFF
    return 10000000.0 if seg == 3 else 10000.0 if seg == 6 else 100.0   # CDS, BCD, everything else


def parse_binary(buf):
    """Kite's binary message -> [{token, ltp, open, high, low, close, volume, oi, t}]. Heartbeats (1 byte) -> []."""
    if len(buf) < 2:
        return []
    n = struct.unpack(">H", buf[:2])[0]
    out, j = [], 2
    for _ in range(n):
        if j + 2 > len(buf):
            break
        ln = struct.unpack(">H", buf[j:j + 2])[0]
        p = buf[j + 2:j + 2 + ln]
        j += 2 + ln
        if len(p) < 8:
            continue
        token = struct.unpack(">I", p[:4])[0]
        d = _div(token)
        tick = {"token": token, "ltp": struct.unpack(">i", p[4:8])[0] / d}
        if len(p) in (28, 32):                     # an index: ltp, high, low, open, close, change (+ time)
            v = struct.unpack(">iiiiii", p[4:28])
            tick.update(high=v[1] / d, low=v[2] / d, open=v[3] / d, close=v[4] / d)
            if len(p) == 32:
                tick["t"] = struct.unpack(">I", p[28:32])[0]
        elif len(p) >= 44:                         # quote / full: ltp, qty, avg, volume, buy, sell, o, h, l, c
            v = struct.unpack(">iiiIIIiiii", p[4:44])
            tick.update(volume=v[3], open=v[6] / d, high=v[7] / d, low=v[8] / d, close=v[9] / d)
            if len(p) >= 64:
                tick["oi"] = struct.unpack(">I", p[48:52])[0]
                tick["t"] = struct.unpack(">I", p[60:64])[0]
        out.append(tick)
    return out


# ------------------------------------------------------------------ what to watch

def wanted():
    keys = list(ALWAYS)
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            led = json.load(fh)
        keys += [p["key"] for p in led.get("open") or [] if p.get("market") in ("NSE", "BSE", "NFO")]
    except (FileNotFoundError, ValueError, KeyError):
        pass
    try:
        with open(WATCH, encoding="utf-8") as fh:
            keys += list(json.load(fh).get("keys") or [])[:2000]
    except (FileNotFoundError, ValueError):
        pass
    out = {}
    for k in dict.fromkeys(keys):
        try:
            out[K.resolve(k)["token"]] = k
        except Exception:
            continue
    return out


# ------------------------------------------------------------------ the stream

class Ticker:
    def __init__(self):
        self.ticks = {}        # paper key -> tick
        self.by_token = {}     # token -> paper key
        self.sub = set()
        self.ws = None
        self.lock = threading.Lock()
        self.last_msg = 0.0

    def on_open(self, ws):
        log("connected to the Kite stream")
        self.sub = set()
        self.resubscribe()

    def resubscribe(self):
        want = wanted()
        with self.lock:
            self.by_token = want
        toks = set(want)
        new, gone = sorted(toks - self.sub), sorted(self.sub - toks)
        if self.ws is None:
            return
        try:
            if new:
                self.ws.send(json.dumps({"a": "subscribe", "v": new}))
                self.ws.send(json.dumps({"a": "mode", "v": ["full", new]}))
            if gone:
                self.ws.send(json.dumps({"a": "unsubscribe", "v": gone}))
                with self.lock:
                    for t in gone:
                        k = want.get(t)
                        self.ticks.pop(k, None)
            if new or gone:
                log("watching %d instruments (+%d, -%d)" % (len(toks), len(new), len(gone)))
            self.sub = toks
        except Exception as e:
            log("subscribe failed: %s" % e)

    def on_message(self, ws, msg):
        self.last_msg = time.time()
        if isinstance(msg, str):
            try:
                d = json.loads(msg)
                if d.get("type") == "error":
                    log("Kite: %s" % d.get("data"))
            except ValueError:
                pass
            return
        now = time.time()
        with self.lock:
            for t in parse_binary(msg):
                k = self.by_token.get(t["token"])
                if k:
                    t["t"] = t.get("t") or now
                    t["received"] = now
                    self.ticks[k] = t

    def on_error(self, ws, err):
        log("stream error: %s" % err)

    def on_close(self, ws, code, reason):
        log("stream closed (%s %s)" % (code, reason))

    def write(self):
        with self.lock:
            doc = {"written": time.time(), "source": "kite websocket", "ticks": dict(self.ticks)}
        tmp = K.TICKS_FILE + ".tmp"
        os.makedirs(os.path.dirname(K.TICKS_FILE), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        os.replace(tmp, K.TICKS_FILE)


def run():
    import websocket
    tk = Ticker()

    def writer():
        n = 0
        while True:
            time.sleep(1)
            n += 1
            try:
                if tk.ws is not None:
                    tk.write()
                if n % 10 == 0:
                    tk.resubscribe()
            except Exception as e:
                log("writer: %s" % e)
    threading.Thread(target=writer, daemon=True).start()

    while True:
        s = K.load_session()
        k, _ = K.keys()
        if not (s and k):
            tk.ws = None
            time.sleep(30)            # not logged in today: wait for Connect Zerodha on the dashboard
            continue
        tk.ws = websocket.WebSocketApp(WS % (k, s["access_token"]), on_open=tk.on_open, on_message=tk.on_message,
                                       on_error=tk.on_error, on_close=tk.on_close)
        tk.ws.run_forever(ping_interval=20, ping_timeout=10)
        tk.ws = None
        time.sleep(5)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) if len(sys.argv) < 2 else sys.argv[1])
    log("kite ticker starting (data only, no orders)")
    run()
