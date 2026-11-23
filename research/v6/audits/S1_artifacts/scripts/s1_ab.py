"""S-1 COUNTERFACTUAL simulator, Phase 3.1: O3 split into two independent switches. Research only; modifies no repo
file. The repo's StructureStream is used unchanged; only the instance's `tracker` attribute is swapped in memory.

The A5 base of an origin candidate is either
  IMMEDIATE  the same-kind swing immediately before the candidate (the CURRENT code), or
  PRE_LEG    the last same-kind swing at or before the BOS reference (the swing before the leg).

  O1     first evaluation IMMEDIATE, late candidate IMMEDIATE          (= official implementation)
  O3A    first evaluation IMMEDIATE, late candidate PRE_LEG            (late-candidate handling, same BOS leg only)
  O3B    first evaluation PRE_LEG,   late candidate IMMEDIATE          (general A5 qualification change)
  O3     first evaluation PRE_LEG,   late candidate PRE_LEG            (= Phase-3 O3_REPLACE_VS_PRE_LEG)

"first evaluation" = the leg's origin is evaluated for the first time (no earlier candidate in this leg);
"late candidate"   = a more extreme candidate of the SAME leg replaces an earlier one (the S-1 path).
Shared sub-rule (all options, as in Phase 3, owner to confirm): a candidate that fails A5 leaves the active protected
swing unchanged (no withdrawal, no fallback).
"""
import os
import sys

V6_ROOT = os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6_ROOT)
from scanner_v6.models import SwingKind  # noqa: E402
from scanner_v6.structure.choch import StructureStream  # noqa: E402
from scanner_v6.structure.protected_levels import OriginNote, ProtectedTracker  # noqa: E402

OPTIONS = {"O1": ("IMMEDIATE", "IMMEDIATE"), "O3A": ("IMMEDIATE", "PRE_LEG"),
           "O3B": ("PRE_LEG", "IMMEDIATE"), "O3": ("PRE_LEG", "PRE_LEG")}


class ABTracker(ProtectedTracker):
    def __init__(self, option, right=2):
        super().__init__(right)
        self.option = option
        self.first_base, self.late_base = OPTIONS[option]
        self.log = []   # (k, bos_id, direction, path FIRST|LATE, old_price, new_price, base_price, qualified, activated)

    def _base(self, swings, kind, p, o, which):
        if which == "PRE_LEG":
            prev = [s for s in swings if s.kind is kind and s.index <= p.ref_index]
        else:
            prev = [s for s in swings if s.kind is kind and s.index < o.index]
        return max(prev, key=lambda s: s.index) if prev else None

    def on_close(self, k, swings):
        keep = []
        for p in self._pending:
            kind = self._need(p.direction)
            cands = [s for s in swings if s.kind is kind and p.ref_index < s.index <= p.bos_index]
            if cands:
                o = min(cands, key=lambda s: s.price) if kind is SwingKind.LOW else max(cands, key=lambda s: s.price)
                if p.origin is None or o.id != p.origin.id:
                    path = "FIRST" if p.origin is None else "LATE"
                    old = p.origin
                    prev_s = self._base(swings, kind, p, o, self.first_base if path == "FIRST" else self.late_base)
                    ok = prev_s is not None and (o.price > prev_s.price if kind is SwingKind.LOW else o.price < prev_s.price)
                    p.origin = o
                    activated = False
                    if not ok:
                        self.notes.append(OriginNote(k, "NOT_QUALIFIED", p.bos_id, o.id,
                                                     "origin %s is not an %s (A5)" % (o.price, "HL" if kind is SwingKind.LOW else "LH")))
                    else:
                        cur = self.active[p.direction]
                        if cur is None or p.bos_index >= cur[0]:
                            self.active[p.direction] = (p.bos_index, o, p.bos_id)
                            activated = True
                            self.notes.append(OriginNote(k, "ACTIVATED", p.bos_id, o.id,
                                                         "protected %s %s activated at the close of index %d, in force from index %d" % (kind.value, o.price, k, k + 1)))
                    self.log.append((k, p.bos_id, p.direction.value, path, old.price if old else None, o.price,
                                     prev_s.price if prev_s else None, ok, activated))
            if k >= p.bos_index + self.right:
                if p.origin is None:
                    self.notes.append(OriginNote(k, "NO_ORIGIN_SWING", p.bos_id, None,
                                                 "no confirmed %s swing in the BOS leg; protected unchanged" % kind.value))
                continue
            keep.append(p)
        self._pending = keep


def run(series, option):
    st = StructureStream()
    st.tracker = ABTracker(option, st.tracker.right)
    ev = []
    for c in series:
        ev.extend(st.on_candle(c))
    return st, ev
