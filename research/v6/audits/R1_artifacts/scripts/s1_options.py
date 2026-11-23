"""S-1 COUNTERFACTUAL simulator (research only; lives OUTSIDE the repo; modifies no repo file).

It reuses the repo's StructureStream unchanged and only swaps, in memory, the instance's `tracker` attribute for a
ProtectedTracker subclass implementing one of the four S-1 options from
research/v6/audits/S1_PROTECTED_RESELECTION_ANALYSIS.md:

  O1 CURRENT   keep the swing already active when a later, lower origin candidate fails A5 (A5 base = the swing
               immediately before the candidate) -- must reproduce the repo output exactly (checked)
  O2 L-A       the final origin of the leg is authoritative; if it fails A5, the activation made by this BOS is
               WITHDRAWN and the protected swing in force before that activation is restored
  O3 REPLACE   A5 for every candidate of a leg is evaluated against the last same-kind swing BEFORE the leg
               (index <= reference.index); a later lower candidate that qualifies replaces the active one; one that
               does not qualify leaves the active one unchanged (sub-rule chosen for simulation; the S-1 doc does not
               say -- labelled)
  O4 EXCL-K    origin candidates exclude the BOS candle itself: window (reference.index, k) instead of (.., k]
"""
import sys

import os as _os
V6_ROOT = _os.environ.get("V6_ROOT", "/home/claude/v6_wt")
sys.path.insert(0, V6_ROOT)
from scanner_v6.models import SwingKind  # noqa: E402
from scanner_v6.structure.choch import StructureStream  # noqa: E402
from scanner_v6.structure.protected_levels import OriginNote, ProtectedTracker  # noqa: E402

OPTIONS = ("O1_CURRENT", "O2_LA_WITHDRAW", "O3_REPLACE_VS_PRE_LEG", "O4_EXCLUDE_BOS_CANDLE")


class AltTracker(ProtectedTracker):
    def __init__(self, option, right=2):
        super().__init__(right)
        self.option = option
        self.snap = {}          # bos_id -> active tuple before this BOS's activation (O2)
        self.s1_events = []     # (k, bos_id, direction, old_origin, new_origin, old_was_active, new_qualified)

    def on_close(self, k, swings):
        keep = []
        for p in self._pending:
            kind = self._need(p.direction)
            hi = p.bos_index - 1 if self.option == "O4_EXCLUDE_BOS_CANDLE" else p.bos_index
            cands = [s for s in swings if s.kind is kind and p.ref_index < s.index <= hi]
            if cands:
                o = min(cands, key=lambda s: s.price) if kind is SwingKind.LOW else max(cands, key=lambda s: s.price)
                if p.origin is None or o.id != p.origin.id:
                    old = p.origin
                    if self.option == "O3_REPLACE_VS_PRE_LEG":
                        prev = [s for s in swings if s.kind is kind and s.index <= p.ref_index]
                    else:
                        prev = [s for s in swings if s.kind is kind and s.index < o.index]
                    prev_s = max(prev, key=lambda s: s.index) if prev else None
                    ok = prev_s is not None and (o.price > prev_s.price if kind is SwingKind.LOW else o.price < prev_s.price)
                    cur = self.active[p.direction]
                    old_active = cur is not None and old is not None and cur[2] == p.bos_id and cur[1].id == old.id
                    if old is not None:
                        self.s1_events.append((k, p.bos_id, p.direction.value, old.price, o.price, old_active, ok))
                    p.origin = o
                    if not ok:
                        self.notes.append(OriginNote(k, "NOT_QUALIFIED", p.bos_id, o.id,
                                                     "origin %s is not an %s (A5)" % (o.price, "HL" if kind is SwingKind.LOW else "LH")))
                        if self.option == "O2_LA_WITHDRAW" and old_active:
                            self.active[p.direction] = self.snap.get(p.bos_id)
                            self.notes.append(OriginNote(k, "WITHDRAWN", p.bos_id, old.id,
                                                         "O2: activation withdrawn, previous protected restored"))
                    else:
                        if cur is None or p.bos_index >= cur[0]:
                            if p.bos_id not in self.snap:
                                self.snap[p.bos_id] = cur if not (cur is not None and cur[2] == p.bos_id) else None
                            self.active[p.direction] = (p.bos_index, o, p.bos_id)
                            self.notes.append(OriginNote(k, "ACTIVATED", p.bos_id, o.id,
                                                         "protected %s %s activated at the close of index %d, in force from index %d" % (kind.value, o.price, k, k + 1)))
            if k >= p.bos_index + self.right:
                if p.origin is None:
                    self.notes.append(OriginNote(k, "NO_ORIGIN_SWING", p.bos_id, None,
                                                 "no confirmed %s swing in the BOS leg; protected unchanged" % kind.value))
                continue
            keep.append(p)
        self._pending = keep


def make_stream(option):
    st = StructureStream()
    st.tracker = AltTracker(option, st.tracker.right)
    return st


def run(series, option):
    st = make_stream(option)
    ev = []
    for c in series:
        ev.extend(st.on_candle(c))
    return st, ev
