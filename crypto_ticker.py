#!/usr/bin/env python3
"""
crypto_ticker.py - live crypto prices from Coinbase's public WebSocket "ticker" channel, written every second to
trader/live/crypto_ticks.json for the dashboard (prices changing every second) and paper.py (stops / targets on
the freshest price).

Public data only: no API key, no authenticated channel, nothing that can place an order. Coinbase pushes a ticker
message on every trade, so the file always holds each coin's last traded price.

Watches: the crypto universe (trader/universe_crypto.txt, the dashboard's coin list) and every open CRYPTO paper
position. The list is re-read every 30 seconds; a change reconnects with the new list. Coins Coinbase does not
list are "missing" (paper.py prices them from Yahoo, as before).

Service: deploy/trader-crypto-ticker.service.   By hand:  python crypto_ticker.py
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

import coinbase as CB

LEDGER = os.path.join("trader", "paper", "ledger.json")
UNIVERSE = os.path.join("trader", "universe_crypto.txt")
DEFAULT_COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC"]
QUIET_S = 60          # no message for this long: the stream is dead, stop writing (paper.py falls back) and reconnect


def log(msg):
    print("%s %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), msg), flush=True)


def wanted():
    coins = []
    try:
        with open(UNIVERSE, encoding="utf-8") as fh:
            coins = [ln.split("|")[0].strip().upper().replace("-USD", "") for ln in fh
                     if ln.strip() and not ln.lstrip().startswith("#")]
    except FileNotFoundError:
        pass
    try:
        with open(LEDGER, encoding="utf-8") as fh:
            led = json.load(fh)
        coins += [p.get("symbol", "").upper() for p in led.get("open") or [] if p.get("market") == "CRYPTO"]
    except (FileNotFoundError, ValueError):
        pass
    return list(dict.fromkeys(c for c in coins if c)) or list(DEFAULT_COINS)


def plan(coins, ids):
    """(product ids to subscribe, coins Coinbase does not list)."""
    subs, missing = [], []
    for c in coins:
        pid = CB.product_of(c, ids)
        (subs.append(pid) if pid else missing.append(c))
    return subs, missing


def subscribe_msg(product_ids):
    """The only message ever sent: a subscription to the public ticker channel (no signature, no key)."""
    return json.dumps({"type": "subscribe", "product_ids": product_ids, "channels": ["ticker"]})


class Ticker:
    def __init__(self):
        self.ticks, self.missing = {}, []
        self.lock = threading.Lock()
        self.last_msg = 0.0
        self.ws = None
        self.subs = []

    def on_open(self, ws):
        ws.send(subscribe_msg(self.subs))
        log("connected to Coinbase; watching %d coins (%d not on Coinbase)" % (len(self.subs), len(self.missing)))

    def on_message(self, ws, msg):
        self.last_msg = time.time()
        try:
            d = json.loads(msg)
        except ValueError:
            return
        if d.get("type") == "error":
            log("Coinbase: %s %s" % (d.get("message"), d.get("reason") or ""))
            return
        if d.get("type") != "ticker" or not str(d.get("product_id", "")).endswith("-USD"):
            return
        try:
            px = float(d["price"])
        except (KeyError, TypeError, ValueError):
            return
        if px <= 0:
            return
        t = d.get("time")
        try:
            ts = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() if t else time.time()
        except ValueError:
            ts = time.time()
        tick = {"ltp": px, "t": ts, "pair": d["product_id"]}
        for src, dst in (("high_24h", "high"), ("low_24h", "low"), ("open_24h", "open")):
            try:
                v = float(d.get(src))
                if v > 0:
                    tick[dst] = v
            except (TypeError, ValueError):
                pass
        if tick.get("open"):
            tick["chg_pct"] = round((px - tick["open"]) / tick["open"] * 100, 3)
        with self.lock:
            self.ticks["CRYPTO:" + d["product_id"][:-4]] = tick

    def on_error(self, ws, err):
        log("stream error: %s" % err)

    def on_close(self, ws, code, reason):
        log("stream closed (%s %s)" % (code, reason))

    def alive(self):
        return self.ws is not None and time.time() - self.last_msg < QUIET_S

    def write(self):
        with self.lock:
            doc = {"written": time.time(), "source": "coinbase public ticker", "ticks": dict(self.ticks),
                   "missing": list(self.missing)}
        os.makedirs(os.path.dirname(CB.TICKS_FILE), exist_ok=True)
        tmp = CB.TICKS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        os.replace(tmp, CB.TICKS_FILE)


def run():
    import websocket
    tk = Ticker()
    state = {"coins": None}

    def writer():
        n = 0
        while True:
            time.sleep(1)
            n += 1
            try:
                if tk.alive():
                    tk.write()
                elif tk.ws is not None and tk.last_msg and time.time() - tk.last_msg >= QUIET_S:
                    tk.ws.close()                      # silent stream: reconnect
                if n % 30 == 0 and tk.ws is not None and wanted() != state["coins"]:
                    log("coin list changed: reconnecting")
                    tk.ws.close()
            except Exception as e:
                log("writer: %s" % e)
    threading.Thread(target=writer, daemon=True).start()

    fails = 0
    while True:
        try:
            state["coins"] = wanted()
            tk.subs, tk.missing = plan(state["coins"], CB.products())
            with tk.lock:
                tk.ticks = {k: v for k, v in tk.ticks.items() if k[7:] + "-USD" in tk.subs}
            tk.last_msg = time.time()
            tk.ws = websocket.WebSocketApp(CB.WS_URL, on_open=tk.on_open, on_message=tk.on_message,
                                           on_error=tk.on_error, on_close=tk.on_close)
            tk.ws.run_forever(ping_interval=20, ping_timeout=10)
            fails = 0
        except Exception as e:
            fails += 1
            log("Coinbase feed failed (%d in a row): %s" % (fails, e))
        tk.ws = None
        time.sleep(min(60, 5 * max(1, fails)))


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) if len(sys.argv) < 2 else sys.argv[1])
    log("crypto ticker starting (Coinbase public ticker; no API key, no orders)")
    run()
