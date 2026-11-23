# Video source notes: what was actually accessed (22 Nov 2026)

**Rule followed:** nothing below claims that a video was watched. **No video file was watched**, because the tools available here cannot play video.

Every statement is tagged with the source it came from:

| Tag | Source | What it is | Reliability |
|---|---|---|---|
| **V1-meta** | YouTube page of `lSRoNosc4zw`, "MASTER Liquidity Concepts in 93 Minutes (Full Trading Course)", Mind Math Money, published 13 May 2026, 1:33:13 | Title, description and **chapter list**. **No transcript or captions on the page.** | Chapters are the creator's own; content beyond the chapter titles is unknown |
| **V1-art** | mindmathmoney.com article "Master Liquidity Concepts Trading: The Complete Guide to Smart Money Strategies" | Written guide by the same creator. It says it accompanies "a YouTube video", but its topic list differs from the 93-minute course: no BSL/SSL as liquidity terms, no run, no internal / external, no inducement. | Creator's own text, but **possibly a different / older video** |
| **V1-AI** | youtubesummary.com summary page for `lSRoNosc4zw` | **AI-generated** third-party summary. No transcript, no timestamps. Its canonical URL matches the video id. | **Unverified.** Used only where marked, never as the creator's words |
| **V2-tx** | Quantsapp page "Liquidity Sweeps and Smart Money Concepts in Price Action" (trainer Ankit Rawat, YouTube id `4LqJ3L4t6JQ`, 16 min, Hindi/English) | **Full auto-generated transcript on the page**, with chapters. The transcript was read through the web tool's extraction, not as raw text; the tool flagged several passages as garbled. | The trainer's words, but garbled in places; no chart images or prices |
| **V3-meta** | YouTube page of `z6osi7TZCZQ`, "Liquidity Sweep Reversals In 3 Simple Steps (No CHoCH Needed)", Justin Bennett, published 13 Jan 2026 | Description and **chapter list**. **No transcript** (YouTube served a bot-protection page; metadata was recovered from the embedded data). | Chapters and description are the creator's own |
| **V3-art** | dailypriceaction.com/blog/liquidity-sweep-reversals/ (Justin Bennett, 30 Jan 2026) | Written strategy article with an embedded ~16-minute video. The target video has a recap chapter at 18:57, so the embedded one is **probably a different video** on the same method. | Creator's own text, same method family |

**Not obtained:** transcripts for V1 and V3. Two transcript-service requests (youtubetranscript.com) were not approved in time.

## V1: Mind Math Money (chapters from V1-meta)

| Time | Chapter (V1-meta) | What is known about the content |
|---|---|---|
| 3:55 | What liquidity is | **V1-art:** how easily an asset can be bought or sold without a big price change |
| 7:37 | High vs low liquidity | **V1-art:** high = many participants, smooth moves, tight spread, normal wicks. Low = choppy, gaps, wide spread, wickless one-direction candles, slippage. **Not testable from OHLC alone** (needs order-book or volume data). |
| 28:16 / 33:16 | Buy-side and sell-side liquidity (BSL/SSL); Bitcoin examples | V1-art discusses only bid / ask order-book sides. **V1-AI:** liquidity clusters at swing highs (above) and lows (below). The video's own definition was **not seen.** |
| 36:55 | Sweeps, grabs and runs. The prompt's sub-chapters 37:11 / 39:26 / 40:36 / 42:21 are **not** in the YouTube chapter list; they may be finer chapters. | **V1-art:** a sweep is the price movement beyond a level. A grab is a deliberate move past a key level to trigger stops, then a reversal: long wick, close back on the original side. A real breakout closes strongly beyond and follows through. **V1-AI:** sweep = a slower break that traps breakout traders, then a sharp reversal. Grab = a faster poke, often a visible wick. Run = a break that continues, preferably a momentum candle (body ≥ 2× the previous) closing far beyond with a small wick. A later close back inside may re-label it a slow sweep. |
| 48:55 | External vs internal liquidity | **V1-AI only:** external = outside the current range (major highs / lows); internal = inside (minor swings, pullbacks); internal tends to be taken before external |
| 52:05 | Liquidity inducement | **V1-AI only:** a counter-trend move that takes internal liquidity, then the larger trend continues. V1-art mentions only small bounces before major levels that bait early entries. |
| 53:58 | High vs low resistance liquidity | **V1-AI only:** low-resistance liquidity sits after a failed swing (weaker); high-resistance after a clean break and reversal (stronger); price tends to take the path of less resistance |
| 59:48 | Equal highs / lows | **V1-art:** a pool location (double tops / bottoms). **V1-AI:** several swing points at one price stack stops into a deeper pool. |
| 1:04:50 | Trendline liquidity | **V1-AI only:** stops sit below rising and above falling trendlines; harder to read, beginners should prefer horizontal levels |

## V2: Quantsapp / Ankit Rawat (V2-tx, chapter times from the page)

| Time | Content (paraphrased from the transcript) |
|---|---|
| 1:15 | A sweep or grab is large players pushing price past an obvious level where small traders hold entries and stops, taking those orders, then reversing. He prefers the word "grab" to "trap". |
| 3:47 | A level rejected twice looks strong, so entries and stops gather just beyond it. That is where the sweep happens. |
| 5:05 | Trendlines and channels: the line is expected to hold, breaks, stops trigger, and price reverses |
| 5:54 | Patterns and equal lows: two lows at one level mean "maximum liquidity" below them |
| 7:10–8:26 | BankNifty 5-minute: points of interest (POI) are marked at the origin candle of a strong move. **The two descriptions are inconsistent:** one zone uses the candle's high / low, the other its open / close. |
| 10:59 | Entry: at a POI, short after a rejection candle (a bearish engulfing example); long after a "clean" break by a green candle. **No objective rejection or breakout rule.** |
| 12:02 | Trap example: price returns to a zone and "took all the SL", then reverses. No prices or candle indices are given. |
| 14:38 | Do not trade the obvious level; wait for the POI |

**Not stated anywhere in V2:** whether a sweep needs a wick beyond, a close beyond, or a close back inside. No numbers, no backtest. The POI and entry method is **this trainer's own approach** (task instruction).

## V3: Justin Bennett (V3-meta chapters; content from V3-meta description and V3-art)

| Time | Chapter (V3-meta) | Known content |
|---|---|---|
| 0:00 / 0:36 | Overview; "Why this isn't a CHoCH (what would make it valid)" | **V3-art:** a CHoCH usually comes later, sometimes much later. A sweep reversal can confirm earlier and gives a better entry; it behaves similarly to a CHoCH. |
| 2:18 | Step 1: established low / high in the trend | **Not defined in V3-art.** V3-art's step 1 instead: a swing high forms inside a 62–79 % retracement zone (OTE). |
| 3:09 | Step 2: sweep / grab (wick vs close) | **V3-meta:** judge the sweep by the wick, not the close. **V3-art:** the sweep is a wick beyond the high; he does not enter on the sweep. |
| 4:42 | Step 3: displacement = buyers / sellers took control | **V3-art:** confirmation is a 15-minute close below the low that triggered the sweep, and "always the close". V3-art does not define displacement numerically. |
| 5:48 | Entry; shallow pullbacks | **V3-art:** enter on that close or a small retrace (FVG / OB retest preferred). Stop beyond the sweep extreme; target the recent low; ≥ 2R, preferably 3R. |
| 7:19 / 10:11 / 14:26 | Examples: EUR (#2), GBP bearish (close below the trigger low), EUR in an uptrend (tiny sweep + confirmation) | V3-art has two EURUSD bearish examples (~2.8R and ~2.5R) and **no bullish example**; it says a buy is the mirror. The video's GBP / EUR candles were **not seen.** |

V3 is a **trade-entry methodology.** Its displacement or close confirmation is part of the reversal setup, **not** of the sweep event (task instruction). Its reported R results are anecdotes, not evidence of profitability.
