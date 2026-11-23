"""BOT for the blind liquidity examination = the CURRENT V6 implementation, unchanged. Reads ONLY the fixtures file
given on the command line; has no path to the answer key. Liquidity questions are answered NOT_IMPLEMENTED because
scanner_v6/liquidity/* are stubs and no detector may be implemented.

    python3 run_bot.py <fixtures.json> <BOT_ANSWERS.json>
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
V6 = os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6)
from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import no_lookahead_violations, replay_audit  # noqa: E402
from scanner_v6.structure.choch import CHoCHBreak, StructureStateChange, StructureStream, analyze_structure, detect_structure  # noqa: E402
import scanner_v6.liquidity.liquidity_pools as LP  # noqa: E402
import scanner_v6.liquidity.sweep as SW  # noqa: E402

assert len(sys.argv) == 3 and "sealed" not in sys.argv[1] and "EXPECTED" not in sys.argv[1].upper()
fx_path, out_path = sys.argv[1], sys.argv[2]
FIX = json.load(open(fx_path))


def liquidity_status():
    """Ask the V6 liquidity modules themselves; they are stubs."""
    res = {}
    for name, mod in (("liquidity_pools", LP), ("sweep", SW)):
        fns = [f for f in dir(mod) if not f.startswith("_") and callable(getattr(mod, f)) and getattr(getattr(mod, f), "__module__", "") == mod.__name__]
        status = "no callable detector"
        for f in fns:
            try:
                getattr(mod, f)(None)
                status = "callable %s returned without error (unexpected)" % f
            except NotImplementedError as e:
                status = "NotImplementedError from %s: %s" % (f, str(e)[:120])
                break
            except Exception as e:
                status = "%s from %s: %s" % (type(e).__name__, f, str(e)[:120])
        res[name] = status
    return res


LIQ = liquidity_status()
answers = []
for sc in FIX["scenarios"]:
    rows = [(datetime.fromisoformat(r["t"].replace("Z", "+00:00")), r["o"], r["h"], r["l"], r["c"], 0) for r in sc["candles"]]
    s = CandleSeries.from_rows(rows, sc["scenario_id"], "5m")
    rep = analyze_structure(s)
    tail_from = 17
    swings = [dict(kind=w.kind.value, price=w.price, source_candle=w.index + 1, confirmed_candle=w.confirmed_index + 1,
                   confidence="deterministic: V6 swings.py (approved SW rules)") for w in rep.swings]
    bos = [dict(direction=b.direction.value, candle=b.index + 1, level=b.level,
                evidence="close %s %s %s" % (s[b.index].close, ">" if b.direction.value == "bullish" else "<", b.level),
                confidence="deterministic: V6 bos.py") for b in rep.bos]
    events = []
    for e in rep.events:
        if isinstance(e, StructureStateChange) and e.cause in ("ESTABLISHED", "REVERSAL_CONFIRMED"):
            p = [t.protected_price for t in rep.timeline if t.index == e.index][0]
            events.append(dict(type=e.cause, candle=e.index + 1, state_after=e.state_after, level=p if e.cause == "ESTABLISHED" else None,
                               confidence="deterministic: V6 choch.py"))
        elif isinstance(e, CHoCHBreak):
            events.append(dict(type="CHOCH", candle=e.index + 1, state_after=e.state_after, level=e.level,
                               evidence="close %s vs protected %s" % (s[e.index].close, e.level), confidence="deterministic: V6 choch.py"))
    diags = [dict(code=d.code, candle=d.index + 1, detail=d.detail) for d in rep.diagnostics]
    wick = [dict(candle=d.index + 1, protected_level=float(d.detail.split("protected ")[1].split(",")[0]),
                 evidence=d.detail, confidence="deterministic: V6 choch.py WICK_ONLY diagnostic")
            for d in rep.diagnostics if d.code == "WICK_ONLY"]
    cps = [dict(candle=t.index + 1, state=t.state, protected=t.protected_price, confidence="deterministic: V6 timeline")
           for t in rep.timeline if t.index + 1 >= tail_from]
    exp = {e.id: e.index for e in detect_structure(s)}
    audit = replay_audit(s, exp, lambda e: e.id, detector=detect_structure, make_stream=StructureStream)
    nla = no_lookahead_violations(detect_structure, s)
    answers.append(dict(
        scenario_id=sc["scenario_id"],
        decidable=dict(swings=swings, bos=bos, structure_events=events, wick_only=wick, checkpoints=cps,
                       harness=dict(no_lookahead_violations=[str(v) for v in nla], replay_audit_ok=audit.ok,
                                    replay_findings=[str(f) for f in audit.findings][:10])),
        diagnostics_all=diags,
        liquidity=dict(pools="NOT_IMPLEMENTED", events="NOT_IMPLEMENTED", pool_states="NOT_IMPLEMENTED",
                       reason="scanner_v6/liquidity modules are stubs (%s); implementing a detector is out of scope by instruction" % json.dumps(LIQ),
                       confidence="n/a")))
doc = dict(bot="V6 research scanner (worktree, unchanged): swings.py, bos.py, protected_levels.py, choch.py, engine.py",
           fixtures_sha256=hashlib.sha256(open(fx_path, "rb").read()).hexdigest(),
           generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), liquidity_module_status=LIQ, answers=answers)
s_ = json.dumps(doc, indent=1, default=str)
open(out_path, "w").write(s_)
print("bot answers", out_path, "sha256", hashlib.sha256(s_.encode()).hexdigest())
