"""
api/_opinion.py - "Your opinion" on a trade or a scanner candidate (owner, 13 Nov 2026).

The owner reviews the bot's decisions (open / closed trades, skipped / blocked candidates) with a fixed set of
questions, so the answers can be counted and compared later (download all -> opinions.csv / live/opinions.jsonl)
and the rules improved from them. Each saved answer keeps a snapshot of the trade (setup, result, R, reason,
levels), so the export reads on its own. Saving again adds a newer version; the latest one counts.

  GET  /api/py/opinion/questions          the questions (the dashboard draws the form from this)
  GET  /api/py/opinion?ref_id=...          the latest answers for one trade / candidate (or null)
  GET  /api/py/opinion/index               {ref_id: saved_at} of everything answered
  POST /api/py/opinion  {"ref": {...}, "answers": {...}}
       ref: {"kind": "position", "key", "entry_time"} | {"kind": "decision", "time", "symbol"}
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

router = APIRouter()
OPINIONS = os.path.join("trader", "live", "opinions.jsonl")   # relative, like paper.py (the API runs in /opt/trader)
IST = timezone(timedelta(hours=5, minutes=30))

# kinds: "open", "closed" (paper trades), "skipped" (skipped / blocked / log only), "traded" (a traded candidate)
MISTAKES = [
    ("bos_invalid", "BOS was not valid (no real close beyond the swing)"),
    ("sweep_invalid", "The sweep was not a real liquidity sweep"),
    ("signal_wrong", "The signal candle was the wrong shape"),
    ("late_entry", "Entered mid-move / too late"),
    ("early_entry", "Entered too early (no confirmation)"),
    ("against_htf", "Against the higher-timeframe trend (POV)"),
    ("choppy", "Choppy or low-volume market"),
    ("bad_time", "Bad time (session open / close / news)"),
    ("opposing_level", "Price was right at an opposing zone or level"),
    ("stop_tight", "Stop too tight"),
    ("stop_wide", "Stop too wide"),
    ("target_near", "Target too near"),
    ("target_far", "Target too far"),
    ("tm_early", "Trade Manager exited too early"),
    ("tm_late", "Trade Manager exited too late / gave back profit"),
    ("filter_wrong_skip", "A filter skipped a good trade"),
    ("should_skip", "This should have been skipped"),
    ("data_mismatch", "The bot's candles differ from my broker chart"),
    ("other", "Something else (explain below)"),
]

QUESTIONS = [
    {"id": "verdict", "type": "choice", "required": True,
     "text": {"open": "Was taking this trade the right call?", "closed": "Was taking this trade the right call?",
              "traded": "Was taking this trade the right call?", "skipped": "Was skipping it the right call?"},
     "options": [["right", "Right"], ["wrong", "Wrong"], ["partly", "Partly right"], ["unsure", "Not sure"]]},
    {"id": "would_take", "type": "choice",
     "text": "Would you have taken this trade yourself?",
     "options": [["yes", "Yes, as it was"], ["yes_changed", "Yes, with a different entry / stop / target"],
                 ["no", "No"]]},
    {"id": "mistakes", "type": "multi", "show_if": {"verdict": ["wrong", "partly"]},
     "text": "What went wrong? (pick all that apply)", "options": [list(m) for m in MISTAKES]},
    {"id": "quality", "type": "scale", "min": 1, "max": 5,
     "text": "Setup quality, 1 (bad) to 5 (textbook)"},
    {"id": "htf", "type": "choice", "text": "The higher timeframes (1h / 4h / D) were",
     "options": [["with", "With the trade"], ["against", "Against it"], ["sideways", "Sideways"],
                 ["unchecked", "Didn't check"]]},
    {"id": "better_entry", "type": "text", "max": 40, "placeholder": "e.g. 22:00, or 'none'",
     "text": "Which candle should the entry have been (IST time)?"},
    {"id": "better_stop", "type": "number", "text": "A better stop price (optional)"},
    {"id": "better_target", "type": "number", "text": "A better target price (optional)"},
    {"id": "rule_change", "type": "text", "max": 600, "long": True,
     "text": "What rule change would fix this? (your words)"},
    {"id": "confidence", "type": "choice", "text": "How sure are you?",
     "options": [["high", "Very sure"], ["medium", "Somewhat"], ["low", "A guess"]]},
    {"id": "notes", "type": "text", "max": 1000, "long": True, "text": "Anything else?"},
]
_Q = {q["id"]: q for q in QUESTIONS}


def ref_id(ref):
    if ref.get("kind") == "position":
        return "pos|%s|%s" % (ref.get("key"), ref.get("entry_time") or "")
    if ref.get("kind") == "decision":
        return "dec|%s|%s" % (ref.get("symbol"), ref.get("time"))
    raise HTTPException(400, "ref.kind must be position or decision")


def _read():
    out = []
    try:
        with open(OPINIONS, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("ref_id"):
                    out.append(r)
    except FileNotFoundError:
        pass
    return out


def latest():
    """{ref_id: the latest saved record}."""
    out = {}
    for r in _read():
        out[r["ref_id"]] = r
    return out


def context(ref):
    """A snapshot of what was answered about: the trade or the candidate, as the bot saw it."""
    if ref["kind"] == "position":
        import paper as P
        led = P.load_ledger(P.load_config())
        for is_open, rows in ((True, led.get("open", [])), (False, list(reversed(led.get("closed", []))))):
            for p in rows:
                if p.get("key") == ref.get("key") and (not ref.get("entry_time") or p.get("entry_time") == ref["entry_time"]):
                    keep = ("key", "market", "symbol", "side", "qty", "entry", "stop", "risk_stop", "target",
                            "entry_time", "exit_time", "exit", "reason", "r", "pnl", "mfe_r", "mae_r", "setup",
                            "setup_name", "scanner", "liquidity", "entry_reason", "v4_signal_at")
                    return dict({k: p.get(k) for k in keep if p.get(k) is not None},
                                kind="open" if is_open else "closed")
        raise HTTPException(404, "no paper position %s" % ref.get("key"))
    import api._chart as CH
    rec = next((r for r in reversed(CH._decisions()) if r.get("time") == ref.get("time")
                and r.get("symbol") == ref.get("symbol")), None)
    if not rec:
        raise HTTPException(404, "no decision %s at %s" % (ref.get("symbol"), ref.get("time")))
    plan, sc = CH._plan(rec)
    res = str(rec.get("result") or "")
    out = {"kind": "traded" if res.startswith("PAPER") else "skipped", "symbol": rec.get("symbol"),
           "time": rec.get("time"), "result": res, "why": rec.get("why"), "setup": rec.get("setup"),
           "setup_name": sc.get("setup_name"), "scanner": sc.get("scanner"), "liquidity": sc.get("liquidity"),
           "side": plan.get("side"), "entry": plan.get("entry"), "stop": plan.get("stop"), "target": plan.get("target")}
    for k in ("BOS_at", "sweep_at", "signal_at", "signal", "bar_end", "rr"):
        if sc.get(k) is not None:
            out[k] = sc[k]
    return {k: v for k, v in out.items() if v is not None}


def clean(answers):
    """Only known questions, typed and bounded; unknown keys or options are refused."""
    out = {}
    for k, v in (answers or {}).items():
        q = _Q.get(k)
        if q is None:
            raise HTTPException(400, "unknown question %r" % k)
        if v in (None, "", []):
            continue
        t = q["type"]
        if t == "choice":
            if v not in [o[0] for o in q["options"]]:
                raise HTTPException(400, "%s: %r is not an option" % (k, v))
            out[k] = v
        elif t == "multi":
            vs = v if isinstance(v, list) else [v]
            bad = [x for x in vs if x not in [o[0] for o in q["options"]]]
            if bad:
                raise HTTPException(400, "%s: %r are not options" % (k, bad))
            out[k] = list(dict.fromkeys(vs))
        elif t == "scale":
            try:
                n = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, "%s must be a whole number" % k)
            if not q["min"] <= n <= q["max"]:
                raise HTTPException(400, "%s must be %d-%d" % (k, q["min"], q["max"]))
            out[k] = n
        elif t == "number":
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, "%s must be a number" % k)
        else:
            out[k] = str(v).strip()[:q.get("max", 500)]
    for q in QUESTIONS:
        if q.get("required") and q["id"] not in out:
            raise HTTPException(400, "please answer: %s" % q["id"])
    if out.get("mistakes") and out.get("verdict") not in ("wrong", "partly"):
        out.pop("mistakes")
    return out


@router.get("/api/py/opinion/questions")
def questions():
    return {"questions": QUESTIONS}


@router.get("/api/py/opinion/index")
def index():
    return {k: r.get("saved_at") for k, r in latest().items()}


@router.get("/api/py/opinion")
def get_opinion(ref_id: str):
    return latest().get(ref_id)


@router.post("/api/py/opinion")
async def save_opinion(request: Request):
    body = await request.json()
    ref = body.get("ref") or {}
    rid = ref_id(ref)
    answers = clean(body.get("answers"))
    ctx = context(ref)
    prev = latest().get(rid)
    rec = {"saved_at": datetime.now(IST).isoformat(timespec="seconds"), "ref_id": rid,
           "ref": {k: ref.get(k) for k in ("kind", "key", "entry_time", "time", "symbol") if ref.get(k)},
           "version": (prev or {}).get("version", 0) + 1, "context": ctx, "answers": answers}
    os.makedirs(os.path.dirname(OPINIONS), exist_ok=True)
    with open(OPINIONS, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return {"ok": True, "ref_id": rid, "version": rec["version"]}


OPINION_COLS = ["saved_at", "version", "kind", "symbol", "side", "setup_name", "scanner", "result", "reason", "r",
                "why", "entry", "stop", "target", "entry_time", "exit_time", "time"] + [q["id"] for q in QUESTIONS]


def opinion_rows():
    """The latest opinion per trade / candidate, flattened for opinions.csv."""
    rows = []
    for r in latest().values():
        c, a = r.get("context") or {}, r.get("answers") or {}
        row = {"saved_at": r.get("saved_at"), "version": r.get("version"), "kind": c.get("kind"),
               "symbol": c.get("key") or c.get("symbol")}
        for k in ("side", "setup_name", "scanner", "result", "reason", "r", "why", "entry", "stop", "target",
                  "entry_time", "exit_time", "time"):
            row[k] = c.get(k)
        for q in QUESTIONS:
            v = a.get(q["id"])
            row[q["id"]] = "; ".join(v) if isinstance(v, list) else v
        rows.append(row)
    return sorted(rows, key=lambda x: x["saved_at"] or "")
