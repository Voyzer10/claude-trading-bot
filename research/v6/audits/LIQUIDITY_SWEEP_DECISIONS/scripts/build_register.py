"""Builds the LQ Decision Register from register_data.py.
    python3 -B build_register.py <out_dir>
Checks before writing anything: question / B0 / alternatives verbatim against UNRESOLVED_DECISIONS.md, allowed statuses,
owner text present for every approved item and absent for every other one, no cycles, decision order consistent."""
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from register_data import (APPROVAL, B17, D, DELEGATED, DELEGATED_LQ, EDGES, EXTERNAL, EXTRA, GAP_DEFS, MVP_NOTES,  # noqa: E402
                           NOT_APPROVED, NOT_VERIFIED, ORDER, OWNER_EXTERNAL, OWNER_LQ, PARTIAL_OPEN, SOFT, SRC,
                           SUPPORT_RULES_TEXT)

OUT = sys.argv[1]
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "..", ".."))
STATUSES = ("APPROVED", "PARTIALLY APPROVED", "PROPOSED", "OPEN")
ids = [d["id"] for d in D]
st = {d["id"]: d["status"] for d in D}
EXT_APPROVED = {o["id"] for o in OWNER_EXTERNAL}


def fail(msg):
    raise SystemExit("CHECK FAILED: " + msg)


# ---------------------------------------------------------------- checks (nothing is written if one fails)
if len(ids) != 22 or len(set(ids)) != 22 or sorted(ids) != ["LQ-%02d" % i for i in range(1, 23)]:
    fail("LQ-01..LQ-22 must each appear exactly once")
for d in D:
    if d["status"] not in STATUSES:
        fail("%s has status %r" % (d["id"], d["status"]))
    if d["id"] in OWNER_LQ and d["id"] in DELEGATED_LQ:
        fail("%s has both direct and delegated owner text" % d["id"])
    owner = d["id"] in OWNER_LQ or d["id"] in DELEGATED_LQ
    if d["status"] in ("APPROVED", "PARTIALLY APPROVED") and not owner:
        fail("%s is %s without owner text" % (d["id"], d["status"]))
    if owner and d["status"] not in ("APPROVED", "PARTIALLY APPROVED"):
        fail("%s has owner text but status %s" % (d["id"], d["status"]))
    if (d["status"] == "PARTIALLY APPROVED") != (d["id"] in PARTIAL_OPEN):
        fail("%s: PARTIALLY APPROVED must name its open part" % d["id"])
for i in NOT_APPROVED:
    if st[i] not in ("PROPOSED", "OPEN"):
        fail("%s must stay unapproved, is %s" % (i, st[i]))
if sorted(i for i in ids if st[i] in ("PROPOSED", "OPEN")) != sorted(NOT_APPROVED):
    fail("the unapproved set does not match NOT_APPROVED")
for i in MVP_NOTES:
    if st[i] == "APPROVED":
        fail("%s carries an MVP-scope note but is APPROVED" % i)
rows = {}
for line in open(os.path.join(ROOT, SRC, "UNRESOLVED_DECISIONS.md"), encoding="utf-8"):
    if line.startswith("| LQ-"):
        c = [x.strip() for x in line.strip().strip("|").split(" | ")]
        rows[c[0].split(" ")[0]] = c
for d in D:
    c = rows.get(d["id"])
    if not c or (c[1], c[2], c[3]) != (d["question"], d["b0"], d["alts"]):
        fail("%s question / B0 / alternatives are not verbatim from UNRESOLVED_DECISIONS.md" % d["id"])
for x in EXTRA:
    if x["id"] not in SUPPORT_RULES_TEXT or not x["status"].startswith("APPROVED"):
        fail("supporting rule %s not recorded as approved with owner text" % x["id"])
for g in GAP_DEFS:
    if (g["status"] == "APPROVED") != bool(g["owner_text"]):
        fail("%s: owner text must exist exactly for approved definitions" % g["id"])
dep_of, blocks = defaultdict(list), defaultdict(list)
for a, b in EDGES:
    dep_of[b].append(a)
    blocks[a].append(b)
color = {}


def dfs(n):
    color[n] = 1
    for m in blocks[n]:
        if color.get(m) == 1:
            fail("cycle via %s -> %s" % (n, m))
        if not color.get(m):
            dfs(m)
    color[n] = 2


for n in sorted(set([a for a, b in EDGES] + [b for a, b in EDGES])):
    if not color.get(n):
        dfs(n)
tier = {}
for t, (title, items) in enumerate(ORDER):
    for it in items:
        tier[it.split(" ")[0]] = t
for a, b in EDGES:
    if a in tier and b in tier and tier[a] > tier[b]:
        fail("order violates dependency %s -> %s" % (a, b))
if [i for i in ids if i not in tier]:
    fail("decisions missing from the order")

cnt = {s: sum(d["status"] == s for d in D) for s in STATUSES}
COUNTS_LQ = "%d APPROVED, %d PARTIALLY APPROVED, %d PROPOSED, %d OPEN" % tuple(cnt[s] for s in STATUSES)
dcnt = {s: sum(1 for d in D if d["id"] in DELEGATED_LQ and d["status"] == s) for s in ("APPROVED", "PARTIALLY APPROVED")}
COUNTS_DEL = "%d APPROVED and %d PARTIALLY APPROVED by delegated decision (%s)" % (dcnt["APPROVED"], dcnt["PARTIALLY APPROVED"], DELEGATED["date"])
COUNTS_EXT = "%d APPROVED (%s)" % (len(OWNER_EXTERNAL), ", ".join(sorted(EXT_APPROVED)))
HEAD = ("**Decision register.** Owner decisions of **%s** and delegated MVP decisions are recorded here; the source documents in `%s` are unchanged.\n\n"
        "- **LQ decisions (LQ-01…LQ-22):** %s; of these, %s.\n"
        "- **External owner decisions (outside LQ):** %s. Counted separately, never added to the LQ counts.\n\n"
        "Status values:\n"
        "- **APPROVED:** explicit owner decision, recorded verbatim with its date.\n"
        "- **OWNER APPROVED — DELEGATED DECISION:** an APPROVED or PARTIALLY APPROVED decision finalized under the owner's\n"
        "  delegated authority for the initial PAPER-ONLY MVP; documented, not implemented (marked per decision).\n"
        "- **PARTIALLY APPROVED:** part of the decision is approved (stated verbatim); the remaining part is named and stays OPEN.\n"
        "- **PROPOSED:** B0 has a concrete proposal; not approved.\n"
        "- **OPEN:** no concrete proposal, or B0 is a placeholder, \"not modelled\" or \"excluded\"; not approved.\n\n"
        "Question, B0 proposal and alternatives are copied **verbatim** from `UNRESOLVED_DECISIONS.md` (checked by the generator:\n"
        "22 / 22 rows match). **No liquidity detector is implemented** (see \"Technical implementation not yet verified\").\n"
        % (APPROVAL["date"], SRC, COUNTS_LQ, COUNTS_DEL, COUNTS_EXT))
short = lambda s: re.split(r"\. (?=[A-Z*])", s)[0].replace("**", "").replace("|", "/")
md = lambda s: s.replace("|", "/")
cut = lambda s, n: s if len(s) <= n else s[:n].rstrip() + "…"

# ---------------------------------------------------------------- register
L = ["# LQ Decision Register: V6 Liquidity Sweep (LQ-01 to LQ-22)", "", HEAD,
     "## What is fixed and what is not", "",
     "| Layer | Status | Content |", "|---|---|---|",
     "| Existing approved structure rules (earlier phases) | **APPROVED** | Swings SW-001…005 (L2/R2 strict, equal levels are not swings), BOS-001…005, Option A, D4, D5 order, CHoCH A1–A10 / D1–D3, D2 P-B, A5, no-look-ahead harness |",
     "| External owner decision | **APPROVED** (%s) | CHU04 STRICT (see \"External owner decisions\") |" % APPROVAL["date"],
     "| Owner-approved liquidity decisions | **APPROVED** (%s) | %s; supporting rules LS-S02, LS-S09, LS-S11, LP-12 pool part; definitions %s |"
     % (APPROVAL["date"], ", ".join(i for i in ids if st[i] == "APPROVED" and i in OWNER_LQ), ", ".join(g["id"] for g in GAP_DEFS if g["status"] == "APPROVED")),
     "| Delegated MVP decisions | **OWNER APPROVED — DELEGATED DECISION** (%s) | APPROVED: %s. PARTIALLY APPROVED: %s |"
     % (DELEGATED["date"], ", ".join(i for i in ids if i in DELEGATED_LQ and st[i] == "APPROVED"), ", ".join(i for i in ids if i in DELEGATED_LQ and st[i] == "PARTIALLY APPROVED")),
     "| Partially approved | **PARTIALLY APPROVED** | %s |" % "; ".join("%s (%s)" % (k, v) for k, v in PARTIAL_OPEN.items()),
     "| Still proposed / open | **PROPOSED / OPEN** | %s; definitions %s |" % (", ".join(i for i in ids if st[i] in ("PROPOSED", "OPEN")), ", ".join(g["id"] for g in GAP_DEFS if g["status"] != "APPROVED")),
     "| Invariants derived from approved rules | INV (not new rules) | LP-01 (pool known only from swing confirmation + 1), LP-11 (no swing → no pool in the first L / last R candles), LS-S10 (S-wick sweep and BOS are mutually exclusive on one level / candle) |",
     "| Technical implementation | **NOT VERIFIED** | No detector, no liquidity tests (see the last section) |", "",
     "Base series used in examples: " + B17 + ". Bearish examples mirror prices (p → 200 − p).", "",
     "## Summary", "", "| ID | Decision | Status | B0 proposal (short) | Owner decision (short) |", "|---|---|---|---|---|"]
for d in D:
    od = OWNER_LQ.get(d["id"]) or DELEGATED_LQ.get(d["id"])
    pre = "(delegated) " if d["id"] in DELEGATED_LQ else ""
    L.append("| [%s](#%s) | %s | **%s** | %s | %s |" % (d["id"], d["id"].lower(), d["title"], d["status"], cut(short(d["b0"]), 100),
                                                       pre + cut(md(" ".join(od)), 160) if od else ("MVP note only" if d["id"] in MVP_NOTES else "–")))
L += ["", "Counts, LQ decisions: %s." % COUNTS_LQ, "", "Of which by delegated decision: %s." % COUNTS_DEL, "",
      "Counts, external owner decisions: %s." % COUNTS_EXT, ""]
for d in D:
    L += ["---", "", "## %s" % d["id"], "", "**%s** · Status: **%s** · Evidence (source tags): %s" % (d["title"], d["status"], d["evidence"]), ""]
    if d["id"] in OWNER_LQ:
        L += ["**Owner decision (%s, verbatim):**" % APPROVAL["date"], ""] + ["> %s" % t for t in OWNER_LQ[d["id"]]] + [""]
    if d["id"] in DELEGATED_LQ:
        L += ["**Owner decision — DELEGATED DECISION (%s, verbatim; %s):**" % (DELEGATED["date"], DELEGATED["label"]), ""] + \
             ["> %s" % t for t in DELEGATED_LQ[d["id"]]] + ["", "Scope: %s" % DELEGATED["scope"], ""]
    if d["id"] in PARTIAL_OPEN:
        L += ["**Still OPEN within this decision:** %s" % PARTIAL_OPEN[d["id"]], ""]
    if d["id"] in MVP_NOTES:
        L += ["**MVP scope note:** %s" % MVP_NOTES[d["id"]], ""]
    L += ["**Unresolved question (verbatim, source):** %s" % d["question"], "",
          "**Proposals / options in the source (verbatim):**",
          "- B0: %s" % d["b0"], "- Alternatives: %s" % d["alts"], "",
          "**What each option would change:**", "", "| Option | Pool detection / event classification / lifecycle / structure |", "|---|---|"]
    for o, e in d["effects"]:
        L.append("| %s | %s |" % (o, md(e)))
    L += ["", "**Minimal OHLC example:** %s" % d["example"], "",
          "**Dependencies:** " + "; ".join(d["deps"]), "",
          "**Pre-approval research note (%s):** %s" % (d["rec"][0], d["rec"][1]), "",
          "**Spec references:** " + "; ".join(d["spec_refs"]), ""]
L += ["---", "", "## Supporting B0 rules without their own LQ id", "",
      "| Rule | Content (spec) | Owner decision (%s, verbatim) | Status | Linked decisions |" % APPROVAL["date"], "|---|---|---|---|---|"]
for x in EXTRA:
    L.append("| %s | %s | %s | %s | %s |" % (x["id"], x["rule"], SUPPORT_RULES_TEXT[x["id"]], x["status"], x["linked"]))
L += ["", "## Supporting definitions (gaps G-1…G-11)", "",
      "| ID | Status | Owner decision (%s, verbatim) | Note |" % APPROVAL["date"], "|---|---|---|---|"]
for g in GAP_DEFS:
    L.append("| %s | **%s** | %s | %s |" % (g["id"], g["status"], md(g["owner_text"]) or "–", md(g["note"]) or "–"))
L += ["", "The full gap descriptions are in `CONTRADICTIONS_AND_GAPS.md` §C.", "",
      "## External owner decisions (outside LQ)", "",
      "Recorded here only. They are prerequisites of LQ decisions, not LQ decisions, and are not counted with them.", ""]
for o in OWNER_EXTERNAL:
    L += ["### %s: %s" % (o["id"], o["status"]), "",
          "- Decision ID: %s" % o["id"], "- Decision: %s" % o["decision"], "- Approval date: %s" % o["approval_date"],
          "- Scope: %s" % o["scope"], "- Rationale: %s" % o["rationale"], "- Equality: %s" % o["equality"], "",
          "Owner decision (verbatim):", ""] + ["> - %s" % t for t in o["owner_text"]] + \
         ["", "Recorded in: %s (source-vs-register traceability: `CONTRADICTIONS_AND_GAPS.md` §E)." % o["recorded_in"], ""]
L += ["## Items outside LQ that LQ decisions depend on", "", "| Item | What it is |", "|---|---|"]
for k, v in EXTERNAL.items():
    L.append("| %s | %s |" % (k, v))
L += ["", "## Technical implementation not yet verified", ""] + ["- %s" % t for t in NOT_VERIFIED] + [""]
REGISTER = "\n".join(L) + "\n"

# ---------------------------------------------------------------- dependency map
CLS = {"APPROVED": "approved", "PARTIALLY APPROVED": "partial", "PROPOSED": "proposed", "OPEN": "open"}
san = lambda x: x.replace("-", "_").replace(" / ", "_").replace(" ", "_")
M = ["flowchart LR"]
for k in EXTERNAL:
    if k in EXT_APPROVED:
        M.append('  %s["%s<br/>(outside LQ)<br/>APPROVED<br/>STRICT, %s"]:::extappr' % (san(k), k, APPROVAL["date"]))
    else:
        M.append('  %s["%s<br/>(outside LQ)<br/>OPEN"]:::ext' % (san(k), k))
for d in D:
    M.append('  %s["%s<br/>%s<br/>%s%s"]:::%s' % (san(d["id"]), d["id"], d["title"].replace('"', "'"), d["status"],
                                                  " (delegated)" if d["id"] in DELEGATED_LQ else "", CLS[d["status"]]))
for a, b in EDGES:
    M.append("  %s --> %s" % (san(a), san(b)))
for a, b in SOFT:
    M.append("  %s -.- %s" % (san(a), san(b)))
M += ["  classDef approved fill:#dff2e4,stroke:#2f7d44,color:#111,stroke-width:2px",
      "  classDef partial fill:#eef7e6,stroke:#2f7d44,color:#111,stroke-dasharray: 5 3",
      "  classDef proposed fill:#e8f1fb,stroke:#3b6fb2,color:#111",
      "  classDef open fill:#fdf0e6,stroke:#b2753b,color:#111",
      "  classDef ext fill:#eeeeee,stroke:#777,color:#111,stroke-dasharray: 4 3",
      "  classDef extappr fill:#dff2e4,stroke:#2f7d44,color:#111,stroke-dasharray: 4 3"]
MER = "\n".join(M) + "\n"
G = ["# LQ dependency map and decision order", "", HEAD,
     "A solid arrow **A → B** means: decide A before B (B's options are defined in terms of A). A dashed line means the two",
     "decisions overlap or interact without a strict order. Node colours: green = APPROVED, light green dashed = PARTIALLY",
     "APPROVED, blue = PROPOSED, orange = OPEN; grey dashed = open item outside the liquidity spec, green dashed = approved item",
     "outside it (CHU04). Rendered: `lq_dependency_map.png`; source: `lq_dependency_map.mmd`.", "",
     "```mermaid", MER.strip(), "```", "",
     "## Dependency table", "", "| Decision | Status | Depends on | Blocks |", "|---|---|---|---|"]
tag = lambda x: x + (" (%s)" % st[x] if x in st else (" (APPROVED, external)" if x in EXT_APPROVED else " (OPEN, external)"))
for i in ids:
    G.append("| %s | %s | %s | %s |" % (i, st[i], ", ".join(tag(x) for x in dep_of[i]) or "–", ", ".join(blocks[i]) or "–"))
G += ["", "## Overlaps / interactions (dashed; no strict order)", "", "| Pair | Nature |", "|---|---|"]
NAT = {("LQ-05", "LQ-02"): "'major' might mean 'external'", ("LQ-02", "LQ-07"): "an age filter (LQ-02) is also an expiry (LQ-07)",
       ("LQ-03", "LQ-14"): "EQ / similar-price pools multiply same-candle events", ("LQ-07", "LQ-14"): "no expiry multiplies same-candle events (LP §C)",
       ("LQ-03", "LQ-19"): "'≥ 2 swings in a band' vs 'repeated S/R'",
       ("O9", "LQ-22"): "a pool TAKEN before the structure establishes, while the CHoCH layer still treats the level as protected (reporting settled by G-11; O9 itself OPEN)"}
for a, b in SOFT:
    G.append("| %s – %s | %s |" % (a, b, NAT.get((a, b), "")))
G += ["", "## Decision order", "",
      "Derived from the dependency edges: a decision is placed after everything it depends on. Tiers 0–3 hold the decisions a",
      "minimal B0 detector needs; tiers 4–5 hold the remaining PROPOSED / OPEN decisions, in the order they can be taken.", ""]
for title, items in ORDER:
    G += ["**%s:** %s" % (title, ", ".join(items)), ""]
G += ["**Status of the minimal B0 decision set (tiers 1–3):** owner-approved on %s (LQ-10 for its B0 scope only). Still open"
      % APPROVAL["date"],
      "outside LQ: O4, BOS-006 / C1 (B0 uses raw float meanwhile, G-8), O7, A1. **No detector is implemented**; implementation",
      "needs separate owner authorization. Test-case status: LT-10 (close == P) is decided in this register (LQ-08 sub-case +",
      "CHU04), although the source TEST_CASE_CATALOG still says UNSCORED. EQ pools (LT-07 / LT-08), expiry (LT-13) and reclaim",
      "(LT-11) still depend on open decisions.", "",
      "**Cycle check:** the edge set was checked for cycles by the generator: none."]
DEPMAP = "\n".join(G) + "\n"

# ---------------------------------------------------------------- json
decisions = []
for d in D:
    e = dict(d)
    e["owner_decision"] = (dict(type="direct", date=APPROVAL["date"], text=OWNER_LQ[d["id"]]) if d["id"] in OWNER_LQ else
                           dict(type="delegated", date=DELEGATED["date"], label=DELEGATED["label"], text=DELEGATED_LQ[d["id"]])
                           if d["id"] in DELEGATED_LQ else None)
    e["mvp_scope_note"] = MVP_NOTES.get(d["id"])
    e["still_open_part"] = PARTIAL_OPEN.get(d["id"])
    decisions.append(e)
JS = json.dumps(dict(
    spec="V6 LQ Decision Register (owner decisions of %s and delegated MVP decisions of %s recorded; source specifications unchanged; no detector implemented)" % (APPROVAL["date"], DELEGATED["date"]),
    approval=APPROVAL, delegated=DELEGATED, source_folder=SRC,
    counts=dict(lq_decisions={s: cnt[s] for s in STATUSES}, lq_delegated=dcnt,
                external_owner_decisions=dict(APPROVED=len(OWNER_EXTERNAL), ids=sorted(EXT_APPROVED))),
    statuses=st, decisions=decisions,
    supporting_rules=[dict(x, owner_text=SUPPORT_RULES_TEXT[x["id"]]) for x in EXTRA],
    supporting_definitions=GAP_DEFS, not_approved=NOT_APPROVED,
    external_dependencies=EXTERNAL, external_owner_decisions=OWNER_EXTERNAL,
    dependency_edges=[dict(decide_first=a, then=b) for a, b in EDGES], overlaps=[dict(a=a, b=b) for a, b in SOFT],
    decision_order=[dict(tier=t, items=i) for t, i in ORDER], not_yet_verified=NOT_VERIFIED), indent=1, ensure_ascii=False)

# ---------------------------------------------------------------- write (only after every check passed)
os.makedirs(OUT, exist_ok=True)
for name, text in (("LQ_DECISION_REGISTER.md", REGISTER), ("DEPENDENCY_MAP.md", DEPMAP), ("lq_dependency_map.mmd", MER),
                   ("lq_decision_register.json", JS)):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(text)
print("register built: 22 decisions (%s), %d edges, no cycles, order consistent, 22 / 22 verbatim" % (COUNTS_LQ, len(EDGES)))
