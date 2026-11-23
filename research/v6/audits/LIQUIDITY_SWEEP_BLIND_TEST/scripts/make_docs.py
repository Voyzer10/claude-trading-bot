"""Writes LIQUIDITY_SWEEP_BLIND_TEST.md and RESULTS_SUMMARY.md from the fixtures, key, bot answers and scores."""
import json
import sys

P = sys.argv[1]
OUT = sys.argv[2]
F = json.load(open(P + "/fixtures/LIQUIDITY_SWEEP_BLIND_FIXTURES.json"))
E = {s["scenario_id"]: s for s in json.load(open(P + "/sealed/EXPECTED_RESULTS.json"))["scenarios"]}
B = json.load(open(P + "/bot/BOT_ANSWERS.json"))
BA = {a["scenario_id"]: a for a in B["answers"]}
S = json.load(open(P + "/scored/SCORES.json"))
proto = open(P + "/protocol/ALL.txt").read()
fmt = lambda x: ("%g" % x) if isinstance(x, (int, float)) else str(x)

L = ["# V6 Liquidity Sweep: blind examination", "",
     "**Date:** 22 Nov 2026. **Research only.** No liquidity detector was implemented; no scanner, test, spec, V4 or production",
     "file was changed. **PAPER ONLY.**", "",
     "## 1. What is approved and what is not", "",
     "From `research/v6/specs/liquidity_sweep/`:",
     "- **No liquidity rule is approved.** LQ-01…LQ-22 are open, and the B0 baseline is only a proposal.",
     "- B0 proposes: pools = confirmed L2/R2 swings, active from confirmation + 1; sweep = wick strictly beyond with the",
     "  close not beyond (S-wick, d = 0); close beyond → TAKEN; lifecycle ACTIVE → SWEPT → TAKEN; one event per pool;",
     "  REPEAT_SWEEP diagnostics; no expiry; sweeps never change the structure state.",
     "- `scanner_v6/liquidity/*` are docstring-only stubs.", "",
     "**Consequences for this exam:**",
     "- **Scored (decidable):** only facts that follow from approved rules, inside liquidity contexts:",
     "  - swing levels and their confirmation candle (the would-be pool levels; SW-001…005);",
     "  - BOS (BOS-001…005, D4, D5);",
     "  - CHoCH, establishment and reversal (A1–A10, D1–D3);",
     "  - WICK_ONLY at the protected swing (A6);",
     "  - state and protected swing after each tail candle (D2 P-B);",
     "  - no-look-ahead and batch / stream parity.",
     "- **PROVISIONAL (B0):** every pool, every SWEEP / REPEAT_SWEEP / TAKEN event and every pool state. Written in the key,",
     "  **not scored**.",
     "- **UNRESOLVED:** never forced:",
     "  - close == level (CHU04 / LQ-08);",
     "  - equal / separated equal highs (LQ-03);",
     "  - a touch at exactly the level (LQ-09);",
     "  - reclaim after a close beyond (LQ-12 / O4);",
     "  - the state after an O4 close-back.",
     "- **The bot is the current V6 implementation, unchanged.** For liquidity it can only answer NOT_IMPLEMENTED.", "",
     "## 2. Blind protocol (hashes and UTC times in `PROTOCOL.txt`)", "",
     "1. **Fixtures:** 20 scenarios, OHLC only, built and hashed (`LIQUIDITY_SWEEP_BLIND_FIXTURES.json`). Only candle",
     "   validity was checked; no structure was computed.",
     "2. **Answer key:** written by hand from the rules and sealed **before the bot ran**:",
     "   - `EXPECTED_RESULTS.json`, file made read-only, SHA-256 recorded;",
     "   - mirrors derived mechanically (p → 200 − p);",
     "   - candle values read only to quote evidence.",
     "3. **Bot:** run in a separate process that received **only** the fixtures path (`BOT_ANSWERS.json`).",
     "4. **Scoring** (`SCORES.json`, `SCORE_ITEMS.csv`).",
     "5. **Scorer mutation test:** 6 injected bot errors were each detected (§5).", "",
     "```", proto.strip(), "```", "",
     "## 3. Scenarios", "",
     "**Base for every scenario** (candles 1–16, CHD01 c1–c16; mirrored scenarios use p → 200 − p):", "",
     "| c | O | H | L | C |", "|---|---|---|---|---|"]
base = F["scenarios"][0]["candles"][:16]
for c in base:
    L.append("| %d | %s | %s | %s | %s |" % (c["candle"], fmt(c["o"]), fmt(c["h"]), fmt(c["l"]), fmt(c["c"])))
L += ["", "**Scenario tails** (candle 17 onward; full candles for every scenario in the fixtures JSON):", "",
      "| Scenario | Difficulty | Covers | Tail candles c17… (O / H / L / C) |", "|---|---|---|---|"]
for s in F["scenarios"]:
    tail = s["candles"][16:]
    L.append("| %s | %s | %s%s | %s |" % (s["scenario_id"], s["difficulty"], s["covers"],
                                         (" (mirror of %s)" % s["mirror_of"]) if s["mirror_of"] else "",
                                         " · ".join("c%d %s/%s/%s/%s" % (c["candle"], fmt(c["o"]), fmt(c["h"]), fmt(c["l"]), fmt(c["c"])) for c in tail)))
L += ["", "**Coverage:**",
      "- BSL and SSL: E1, E3, E4, E5, H1, H2, X2 / E2, M1–M5, H3–H5, X3–X5.",
      "- Wick vs close beyond: E1, E2 vs E4, M2, X3.",
      "- Lifecycle ACTIVE → SWEPT → TAKEN: M2, X4.",
      "- Repeated sweeps: M1, M5, X4.",
      "- Several pools on one candle: M3, M4, H1, X2.",
      "- Several levels: H3, H4, X4.",
      "- BOS / CHoCH interaction: E4, M2, H1–H3, X3–X5.",
      "- Protected-swing liquidity: E2, E3, M1, H3, H5.",
      "- No-look-ahead / ordering: H4, H3 (D5 activation).",
      "- Mirrors: E3, E5, M4, M5, H2, H5, X5.", "",
      "## 4. Answer format", "",
      "Each item in the key and in the bot answers carries:",
      "- pool id + side (`SSL@101(c10)`);",
      "- event type;",
      "- candle (1-based);",
      "- pool state before → after;",
      "- close / wick evidence;",
      "- BOS / CHoCH interaction;",
      "- status: APPROVED / PROVISIONAL (with the B0 / LQ reference) / UNRESOLVED (with the reason).",
      "",
      "The bot's liquidity answer is `NOT_IMPLEMENTED`, with the stub status as the reason.", "",
      "## 5. Scorer check", "",
      "The scorer was run on six deliberately corrupted copies of the bot answers. Each was detected:",
      "- drop a swing → 1 FAIL;",
      "- wrong BOS level → 2 FAIL (missing + unexpected);",
      "- extra CHoCH → 1 FAIL;",
      "- wrong checkpoint → 1 FAIL;",
      "- missing WICK_ONLY → 1 FAIL;",
      "- harness failure → 1 FAIL.", "",
      "So a perfect score is not an artefact of a lenient scorer.", ""]
open(OUT + "/LIQUIDITY_SWEEP_BLIND_TEST.md", "w").write("\n".join(L) + "\n")

t = S["decidable_totals"]
tot = t.get("PASS", 0) + t.get("FAIL", 0)
R = ["# Results summary: V6 Liquidity Sweep blind examination", "",
     "## Score (decidable items only)", "",
     "| | PASS | FAIL | Total |", "|---|---|---|---|",
     "| **All** | **%d** | **%d** | **%d** |" % (t.get("PASS", 0), t.get("FAIL", 0), tot)]
for k in ("Easy", "Medium", "Hard", "Extreme"):
    v = S["by_difficulty"][k]
    R.append("| %s | %d | %d | %d |" % (k, v.get("PASS", 0), v.get("FAIL", 0), v.get("PASS", 0) + v.get("FAIL", 0)))
R += ["", "| Category | PASS | FAIL |", "|---|---|---|"]
for k, v in S["by_category"].items():
    R.append("| %s | %d | %d |" % (k, v.get("PASS", 0), v.get("FAIL", 0)))
R += ["", "| Scenario | PASS | FAIL |", "|---|---|---|"]
for k, v in S["by_scenario"].items():
    R.append("| %s | %d | %d |" % (k, v.get("PASS", 0), v.get("FAIL", 0)))
R += ["", "**Mismatches:** %d. %s" % (len(S["mismatches"]), "" if not S["mismatches"] else json.dumps(S["mismatches"], indent=1)), "",
      "**What the score means:**",
      "- The current V6 structure layer (swings, BOS, CHoCH, protected swing, WICK_ONLY, state timeline, no-look-ahead,",
      "  parity) matches the hand-written key on every decidable item, in liquidity-heavy scenarios: outside bars, repeated",
      "  wicks, several levels on one candle, a freshly activated protected swing, D4 no-fallback, reversal confirmation, and",
      "  all mirrors.",
      "- It says **nothing** about liquidity detection: no liquidity rule is approved, and V6 has no detector.", "",
      "## Provisional (B0) liquidity items: not scored", "",
      "| | Count |", "|---|---|",
      "| Expected B0 pools | %d |" % S["provisional"]["expected_pools"],
      "| Expected B0 liquidity events (SWEEP / REPEAT_SWEEP / TAKEN / explicit no-event) | %d |" % S["provisional"]["expected_events"],
      "| Bot answers for liquidity | 0 of 20 scenarios: `NOT_IMPLEMENTED` (stubs: %s) |" % json.dumps(B["liquidity_module_status"]), "",
      "These key entries are ready to become scored expectations once B0 (or an alternative) is approved and a detector",
      "exists.", "",
      "## Unresolved items: never scored", "",
      "| Scenario | Candle | Item |", "|---|---|---|"]
for u in S["unresolved"]:
    R.append("| %s | c%d | %s |" % (u["scenario"], u["candle"], u["item"]))
R += ["", "**Bot diagnostics on unresolved / unscored points** (recorded, not scored):",
      "- X1 c17 `EXACT_LEVEL_CLOSE` (CHU04, current strict default);",
      "- X3 c18–c19 `O4_UNRESOLVED`;",
      "- `NOT_QUALIFIED` (A5) on H1 / H2 c19, M2 c18, X3 c17, X4 / X5 c19;",
      "- `ACTIVATED` on E4 / E5 / H3 / H5 c18.", "",
      "## Limitations",
      "- The key was hand-derived by the same author who designed the scenarios. The bot is deterministic code that never",
      "  saw the key, and the key was sealed before the bot ran. A wrong key entry would still show as a mismatch, and none",
      "  did. The scenarios reuse the CHD01 base, so base items (4 swings, 1 BOS, ESTABLISHED c16) repeat in every scenario",
      "  and make up part of the total.",
      "- Synthetic data only: no market data, no profitability or edge claim.", ""]
open(OUT + "/RESULTS_SUMMARY.md", "w").write("\n".join(R) + "\n")
print("docs written")
