#!/usr/bin/env python3
"""G12: the oracle-based replay audit (engine.replay_audit). Each deliberately faulty toy detector must be caught in
exactly the expected category, and a correct detector must pass with no finding. The toy detectors have NO trading
meaning: they emit the oracle's own events at chosen times. Offline.

    python tests/scanner_v6/test_replay_audit.py      (or: python -m pytest tests/scanner_v6)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import load_fixture, raises, run_main  # noqa: E402

from scanner_v6.data.candle_models import CandleSeries  # noqa: E402
from scanner_v6.engine import replay_audit  # noqa: E402
from scanner_v6.models import EventStamp, SwingKind, SwingPoint  # noqa: E402

S = CandleSeries.from_chart_json(load_fixture(), "SYN", "5m")
N = len(S)
# oracle: toy events at source candle i, confirmed at i + 2 (i = 10, 30, 50, 70, 90)
ORACLE = {("toy", i): i + 2 for i in (10, 30, 50, 70, 90)}
KEY = lambda e: ("toy", e.index)          # noqa: E731


def ev(i, conf, price=None, eid=None):
    c, k = S[i], S[conf]
    return SwingPoint(eid or "toy:%d" % i, EventStamp(i, c.ts, conf, k.ts), kind=SwingKind.HIGH,
                      price=price if price is not None else c.high)


# ---- batch-mode toy detectors: called with a prefix, return everything they consider known ----------------------
def make_batch(shift=0, drop=(), dup=(), repaint=(), only_full_len=None, conf_shift=0):
    """shift: emit `shift` candles after (+) / before (-) the oracle time; drop: oracle sources never emitted;
    dup: sources emitted twice (second id); repaint: sources whose price depends on the prefix length."""
    def det(series):
        k = len(series) - 1
        out = []
        for (_, i), c in ORACLE.items():
            if i in drop:
                continue
            show_at = c + shift
            if show_at > k or show_at < 0:
                continue
            conf = min(c + conf_shift, k) if conf_shift else c
            if conf_shift < 0:
                conf = c + conf_shift
            price = S[k].close if i in repaint else None
            out.append(ev(i, conf, price))
            if i in dup:
                out.append(ev(i, conf, price, eid="toy:%d:again" % i))
        return out
    return det


class Stream:
    """Streaming toy: on candle k, emit the oracle events whose (time + shift) is k."""

    def __init__(self, shift=0, drop=(), extra=()):
        self.shift, self.drop, self.extra = shift, set(drop), set(extra)

    def on_candle(self, candle):
        k = candle.index
        out = [ev(i, c) for (_, i), c in ORACLE.items() if c + self.shift == k and i not in self.drop]
        out += [ev(i, i + 2) for i in self.extra if i + 2 == k]
        return out


def audit(**kw):
    return replay_audit(S, ORACLE, KEY, **kw)


# 1. correct emission at the expected confirmation index
def test_1_correct_detector_passes_batch_and_stream():
    a = audit(detector=make_batch(), make_stream=lambda: Stream())
    assert a.ok, a.findings


# 2. one candle too early (and it claims a confirmation it does not have yet)
def test_2_one_candle_early_is_caught():
    a = audit(detector=make_batch(shift=-1))
    assert "early" in a.categories() and "premature" in a.categories(), a.findings
    a2 = audit(make_stream=lambda: Stream(shift=-1))
    assert "early" in a2.categories() and "premature" in a2.categories(), a2.findings


# 3. one candle too late (the event appears a candle after its confirmation)
def test_3_one_candle_late_is_caught():
    a = audit(detector=make_batch(shift=+1))
    assert "late" in a.categories(), a.findings
    assert any("expected at k=" in m for m in a.findings["late"]), a.findings["late"]
    a2 = audit(make_stream=lambda: Stream(shift=+1))
    assert "late" in a2.categories(), a2.findings


# 4. expected event never emitted
def test_4_missing_event_is_caught():
    a = audit(detector=make_batch(drop=(50,)), make_stream=lambda: Stream(drop=(50,)))
    assert a.categories() == ["missing"], a.findings
    assert len(a.findings["missing"]) == 2      # once per mode


# 5. duplicate event (two ids for one expected event)
def test_5_duplicate_event_is_caught():
    a = audit(detector=make_batch(dup=(30,)))
    assert "duplicate" in a.categories(), a.findings


# 6. emitted in batch but missing in streaming
def test_6_batch_only_is_caught():
    a = audit(detector=make_batch(), make_stream=lambda: Stream(drop=(70,)))
    assert "batch_only" in a.categories() and "missing" in a.categories(), a.findings
    assert any("toy:70" in m for m in a.findings["batch_only"])


# 7. emitted in streaming but absent from batch
def test_7_stream_only_is_caught():
    a = audit(detector=make_batch(drop=(90,)), make_stream=lambda: Stream())
    assert "stream_only" in a.categories(), a.findings
    assert any("toy:90" in m for m in a.findings["stream_only"])


# 8. confirmed event changes or disappears after later candles
def test_8_repaint_is_caught():
    a = audit(detector=make_batch(repaint=(10,)))
    assert "repaint" in a.categories(), a.findings
    assert any("toy:10 changed" in m for m in a.findings["repaint"])

    def vanishing(series):           # emits toy:30 only while the prefix is short, then drops it
        k = len(series) - 1
        out = [ev(i, c) for (_, i), c in ORACLE.items() if c <= k and not (i == 30 and k >= 40)]
        return out
    a2 = audit(detector=vanishing)
    assert "repaint" in a2.categories() and any("disappeared" in m for m in a2.findings["repaint"]), a2.findings


def test_extra_unexpected_event_is_caught():
    a = audit(make_stream=lambda: Stream(extra=(20,)))
    assert a.categories() == ["unexpected"], a.findings


def test_parity_time_mismatch_is_caught():
    a = replay_audit(S, None, None, detector=make_batch(), make_stream=lambda: Stream(shift=+1))
    assert "parity_time" in a.categories() and "late" in a.categories(), a.findings


def test_old_harness_alone_misses_late_and_missing():
    """Documents G12: the unchanged no_lookahead_violations() passes a late detector and a detector that never
    emits an event. replay_audit() catches both (tests 3 and 4)."""
    from scanner_v6.engine import no_lookahead_violations
    assert no_lookahead_violations(make_batch(shift=+1), S) == []
    assert no_lookahead_violations(make_batch(drop=(50,)), S) == []


def test_audit_argument_checks():
    assert raises(ValueError, replay_audit, S)
    assert raises(ValueError, replay_audit, S, ORACLE, None, make_batch())


if __name__ == "__main__":
    run_main([v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)])
