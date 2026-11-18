"""
autolib.py - small helpers the auto_* agent pipelines share: their rules file, the decision log and
Yahoo headlines. Standard library only.
"""
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LIVE_DIR = os.path.join("trader", "live")
DECISIONS = os.path.join(LIVE_DIR, "decisions.jsonl")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def load_rules(path, defaults):
    """The rules file merged over its defaults; written with the defaults on first run."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(defaults, fh, indent=2)
    cfg = dict(defaults)
    with open(path, encoding="utf-8") as fh:
        cfg.update(json.load(fh))
    return cfg


def record(rec):
    """One agent decision, appended to trader/live/decisions.jsonl (the dashboard reads it)."""
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(DECISIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def headlines(yahoo_symbol, region="US", lang="en-US", n=3):
    """The latest Yahoo Finance headlines for a symbol like BTC-USD or RELIANCE.NS."""
    url = ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=%s&lang=%s"
           % (urllib.parse.quote(yahoo_symbol), region, lang))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        out.append({"title": (item.findtext("title") or "").strip(),
                    "published": (item.findtext("pubDate") or "").strip(),
                    "link": (item.findtext("link") or "").strip()})
        if len(out) >= n:
            break
    return out
