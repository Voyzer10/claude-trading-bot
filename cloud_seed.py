#!/usr/bin/env python3
"""
cloud_seed.py - copy the PC bot's files (paper ledger, rules, state, logs) to the cloud runner, once,
so it continues from where the PC left off instead of starting a fresh paper account.

    python cloud_seed.py https://your-app.vercel.app <INGEST_TOKEN>

Stop the PC runner first (python live.py), or both will trade the same paper account.
"""
import json
import os
import sys
import urllib.request

FILES = ["trader/live/state.json", "trader/live/log.txt", "trader/live/decisions.jsonl",
         "trader/live/auto_config.json", "trader/paper/config.json", "trader/paper/ledger.json",
         "trader/universe_crypto.txt", "trader/watchlist.json"]


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    url, token = sys.argv[1].rstrip("/"), sys.argv[2]
    files = {}
    for rel in FILES:
        path = os.path.join(*rel.split("/"))
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                files[rel] = fh.read()
    body = json.dumps({"files": files}).encode()
    req = urllib.request.Request(url + "/api/py/seed", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=60) as r:
        print(r.read().decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
