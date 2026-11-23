# Appendix A — Concrete event timelines (V6 actual output, read-only)

Columns: k = zero-based candle index; pre-state / pre-protected = in force before candle k (D5 step 2); events and swings at k's close; 'protected for k+1' = V6 timeline. Where shown, the last column is the protected level under the alternative non-sticky P-B reading (independent oracle).

#### ME03 candles 88..104
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 | incremental_nonsticky |
|---|---|---|---|---|---|---|---|---|---|
| 88 | 95.3889 / 95.82 / 95.0879 / 95.1832 | BEARISH | 99.3881 | – | – | – | BEARISH | 99.3881 | 99.3881 |
| 89 | 94.8543 / 95.3624 / 94.5556 / 94.8411 | BEARISH | 99.3881 | – | – | – | BEARISH | 99.3881 | 99.3881 |
| 90 | 94.8015 / 95.1947 / 94.4458 / 95.1033 | BEARISH | 99.3881 | – | – | – | BEARISH | 99.3881 | 99.3881 |
| 91 | 94.9123 / 95.3283 / 94.4835 / 94.803 | BEARISH | 99.3881 | – | – | – | BEARISH | 99.3881 | 99.3881 |
| 92 | 94.9938 / 95.716 / 94.7232 / 95.2407 | BEARISH | 99.3881 | – | L@90=94.4458 | – | BEARISH | 99.3881 | 99.3881 |
| 93 | 95.2696 / 95.4567 / 94.7354 / 94.9539 | BEARISH | 99.3881 | – | – | – | BEARISH | 99.3881 | 99.3881 |
| 94 | 94.5985 / 95.4839 / 94.1619 / 95.1642 | BEARISH | 99.3881 | – | H@92=95.716 | – | BEARISH | 99.3881 | 99.3881 |
| 95 | 95.6389 / 96.186 / 94.1868 / 94.5246 | BEARISH | 99.3881 | – | – | – | BEARISH | 99.3881 | 99.3881 |
| 96 | 94.8205 / 94.9592 / 93.8172 / 94.2192 | BEARISH | 99.3881 | BOS bearish vs 94.4458 | – | ACTIVATED(protected high 95.716 activated at the close of index 96, in) | BEARISH | 95.716 | 95.716 |
| 97 | 94.0547 / 95.4721 / 93.9451 / 95.3054 | BEARISH | 95.716 | – | H@95=96.186 | NOT_QUALIFIED(origin 96.186 is not an LH (A5) (bos:bearish:swing:low:90:fi) | BEARISH | 95.716 | 99.3881 |
| 98 | 95.601 / 96.081 / 94.1517 / 94.5811 | BEARISH | 95.716 | – | L@96=93.8172 | WICK_ONLY | BEARISH | 95.716 | 99.3881 |
| 99 | 94.4299 / 95.5079 / 94.2113 / 95.1753 | BEARISH | 95.716 | – | – | – | BEARISH | 95.716 | 99.3881 |
| 100 | 95.3619 / 95.8804 / 94.872 / 95.7289 | BEARISH | 95.716 | CHoCH bullish vs 95.716 (['high', '92']); STATE BEARISH->TRANSITION(bullish) [CHOCH] | H@98=96.081 | – | TRANSITION(bullish) | None | 99.3881 |
| 101 | 95.1694 / 96.3033 / 94.7215 / 95.8709 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None | 99.3881 |
| 102 | 95.7003 / 96.6168 / 95.2462 / 96.0814 | TRANSITION(bullish) | None | STATE TRANSITION(bullish)->BULLISH [REVERSAL_CONFIRMED]; BOS bullish vs 96.081 | – | – | BULLISH | None | 99.3881 |
| 103 | 96.4614 / 96.8118 / 95.7312 / 96.2005 | BULLISH | None | – | – | – | BULLISH | None | 99.3881 |
| 104 | 95.9742 / 97.4872 / 95.4656 / 97.1598 | BULLISH | None | – | – | NO_ORIGIN_SWING | BULLISH | None | 99.3881 |

#### chart_06/HV06 candles 44..56
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 | incremental_nonsticky |
|---|---|---|---|---|---|---|---|---|---|
| 44 | 1193.699951171875 / 1194.300048828125 / 1192.5999755859375 / 1193.300048828125 | TRANSITION(bullish) | None | – | L@42=1189.0 | – | TRANSITION(bullish) | None | None |
| 45 | 1193.5 / 1195.9000244140625 / 1193.0 / 1194.5 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None | None |
| 46 | 1194.0999755859375 / 1194.5 / 1193.5999755859375 / 1194.0 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None | None |
| 47 | 1194.199951171875 / 1195.0 / 1192.4000244140625 / 1195.0 | TRANSITION(bullish) | None | – | H@45=1195.9000244140625 | – | TRANSITION(bullish) | None | None |
| 48 | 1195.0 / 1195.0 / 1193.0 / 1194.0 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None | None |
| 49 | 1194.4000244140625 / 1194.4000244140625 / 1193.0999755859375 / 1194.0 | TRANSITION(bullish) | None | – | L@47=1192.4000244140625 | – | TRANSITION(bullish) | None | None |
| 50 | 1194.0 / 1194.0 / 1191.5 / 1192.9000244140625 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None | None |
| 51 | 1193.0 / 1199.0 / 1193.0 / 1196.699951171875 | TRANSITION(bullish) | None | STATE TRANSITION(bullish)->BULLISH [REVERSAL_CONFIRMED]; BOS bullish vs 1195.9000244140625 | – | ACTIVATED(protected low 1192.4000244140625 activated at the close of i) | BULLISH | 1192.4000244140625 | 1192.4000244140625 |
| 52 | 1196.800048828125 / 1198.9000244140625 / 1195.5999755859375 / 1198.9000244140625 | BULLISH | 1192.4000244140625 | – | L@50=1191.5 | NOT_QUALIFIED(origin 1191.5 is not an HL (A5) (bos:bullish:swing:high:45:f) | BULLISH | 1192.4000244140625 | None |
| 53 | 1199.0 / 1202.300048828125 / 1199.0 / 1201.5 | BULLISH | 1192.4000244140625 | – | – | – | BULLISH | 1192.4000244140625 | None |
| 54 | 1201.699951171875 / 1203.0 / 1200.0 / 1201.5 | BULLISH | 1192.4000244140625 | – | – | – | BULLISH | 1192.4000244140625 | None |
| 55 | 1201.5 / 1203.5 / 1200.199951171875 / 1202.4000244140625 | BULLISH | 1192.4000244140625 | – | – | – | BULLISH | 1192.4000244140625 | None |
| 56 | 1203.0 / 1204.5999755859375 / 1200.199951171875 / 1200.300048828125 | BULLISH | 1192.4000244140625 | – | – | – | BULLISH | 1192.4000244140625 | None |

#### EX02 candles 12..30
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 | incremental_nonsticky |
|---|---|---|---|---|---|---|---|---|---|
| 12 | 97.5419 / 98.0991 / 96.6696 / 97.8807 | UNKNOWN | None | – | H@10=99.0403 | – | UNKNOWN | None | None |
| 13 | 98.1051 / 98.5426 / 96.5877 / 96.7505 | UNKNOWN | None | – | L@11=96.4395 | – | UNKNOWN | None | None |
| 14 | 96.5559 / 97.9743 / 96.1192 / 97.311 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 15 | 97.0591 / 100.3581 / 96.1161 / 100.1068 | UNKNOWN | None | BOS bullish vs 99.0403 | – | ACTIVATED(protected low 96.4395 activated at the close of index 15, in) | UNKNOWN | None | None |
| 16 | 100.4127 / 102.1782 / 99.7958 / 101.6179 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 17 | 101.7072 / 103.9075 / 100.9656 / 102.9444 | UNKNOWN | None | – | L@15=96.1161 | NOT_QUALIFIED(origin 96.1161 is not an HL (A5) (bos:bullish:swing:high:10:) | UNKNOWN | None | None |
| 18 | 102.6254 / 103.7967 / 102.3863 / 103.707 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 19 | 104.0753 / 104.9404 / 102.9972 / 103.8901 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 20 | 104.0801 / 104.9404 / 101.9093 / 102.6136 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 21 | 102.6602 / 103.1665 / 100.8499 / 101.3184 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 22 | 101.4127 / 102.0947 / 100.7381 / 101.5899 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 23 | 101.6273 / 103.0925 / 100.8183 / 102.4292 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 24 | 102.5105 / 102.7227 / 101.9136 / 102.0404 | UNKNOWN | None | – | L@22=100.7381 | – | UNKNOWN | None | None |
| 25 | 102.5466 / 103.7227 / 99.5393 / 100.1828 | UNKNOWN | None | BOS bearish vs 100.7381 | – | – | UNKNOWN | None | None |
| 26 | 100.3672 / 101.1086 / 98.7622 / 98.9858 | UNKNOWN | None | – | – | – | UNKNOWN | None | None |
| 27 | 99.3424 / 100.6835 / 99.0969 / 100.5087 | UNKNOWN | None | STATE UNKNOWN->BULLISH [ESTABLISHED] | H@25=103.7227 | NOT_QUALIFIED(origin 103.7227 is not an LH (A5) (bos:bearish:swing:low:22:) | BULLISH | 96.4395 | None |
| 28 | 100.9981 / 101.5616 / 98.6134 / 98.9971 | BULLISH | 96.4395 | – | – | – | BULLISH | 96.4395 | None |
| 29 | 99.2907 / 99.7458 / 97.616 / 98.4684 | BULLISH | 96.4395 | – | – | – | BULLISH | 96.4395 | None |
| 30 | 98.8378 / 99.1047 / 97.616 / 98.8693 | BULLISH | 96.4395 | – | H@28=101.5616 | – | BULLISH | 96.4395 | None |

#### CHD10 candles 14..23
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 14 | 115.0 / 115.0 / 110.0 / 111.0 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 15 | 111.0 / 112.0 / 106.0 / 107.0 | UNKNOWN | None | STATE UNKNOWN->BULLISH [ESTABLISHED] | H@13=116.0 | – | BULLISH | 101.0 |
| 16 | 107.0 / 108.0 / 103.0 / 104.0 | BULLISH | 101.0 | – | – | – | BULLISH | 101.0 |
| 17 | 104.0 / 105.0 / 99.0 / 100.0 | BULLISH | 101.0 | CHoCH bearish vs 101.0 (['low', '9']); STATE BULLISH->TRANSITION(bearish) [CHOCH]; BOS bearish vs 101.0 | – | NOT_QUALIFIED(origin 116.0 is not an LH (A5) (bos:bearish:swing:low:9:fixe) | TRANSITION(bearish) | None |
| 18 | 100.0 / 101.0 / 97.0 / 98.0 | TRANSITION(bearish) | None | – | – | – | TRANSITION(bearish) | None |
| 19 | 98.0 / 100.5 / 97.5 / 100.0 | TRANSITION(bearish) | None | – | – | – | TRANSITION(bearish) | None |
| 20 | 100.0 / 103.0 / 99.5 / 100.5 | TRANSITION(bearish) | None | – | L@18=97.0 | – | TRANSITION(bearish) | None |
| 21 | 100.5 / 102.5 / 99.0 / 99.5 | TRANSITION(bearish) | None | – | – | – | TRANSITION(bearish) | None |
| 22 | 99.5 / 100.0 / 98.0 / 98.5 | TRANSITION(bearish) | None | – | H@20=103.0 | – | TRANSITION(bearish) | None |
| 23 | 98.5 / 99.0 / 95.0 / 96.0 | TRANSITION(bearish) | None | STATE TRANSITION(bearish)->BEARISH [REVERSAL_CONFIRMED]; BOS bearish vs 97.0 | – | ACTIVATED(protected high 103.0 activated at the close of index 23, in ) | BEARISH | 103.0 |

#### chart_09/HV09 candles 28..40
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 28 | 412.29998779296875 / 412.5 / 412.25 / 412.29998779296875 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 29 | 412.29998779296875 / 412.45001220703125 / 412.25 / 412.29998779296875 | BULLISH | 409.1499938964844 | – | L@27=412.1499938964844 | – | BULLISH | 409.1499938964844 |
| 30 | 412.25 / 412.8500061035156 / 412.25 / 412.54998779296875 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 31 | 412.70001220703125 / 412.70001220703125 / 412.29998779296875 / 412.54998779296875 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 32 | 412.5 / 412.70001220703125 / 412.3999938964844 / 412.3999938964844 | BULLISH | 409.1499938964844 | – | H@30=412.8500061035156 | – | BULLISH | 409.1499938964844 |
| 33 | 412.25 / 412.70001220703125 / 412.0 / 412.70001220703125 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 34 | 412.6000061035156 / 413.3500061035156 / 412.6000061035156 / 413.04998779296875 | BULLISH | 409.1499938964844 | BOS bullish vs 412.8500061035156 | – | – | BULLISH | 409.1499938964844 |
| 35 | 412.95001220703125 / 415.0 / 412.79998779296875 / 415.0 | BULLISH | 409.1499938964844 | – | L@33=412.0 | NOT_QUALIFIED(origin 412.0 is not an HL (A5) (bos:bullish:swing:high:30:fi) | BULLISH | 409.1499938964844 |
| 36 | 414.70001220703125 / 416.54998779296875 / 414.70001220703125 / 416.45001220703125 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 37 | 416.25 / 416.5 / 415.6000061035156 / 416.29998779296875 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 38 | 416.3500061035156 / 416.3999938964844 / 415.6000061035156 / 416.0 | BULLISH | 409.1499938964844 | – | H@36=416.54998779296875 | – | BULLISH | 409.1499938964844 |
| 39 | 416.0 / 416.20001220703125 / 415.6000061035156 / 415.8500061035156 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |
| 40 | 415.8500061035156 / 416.0 / 415.6000061035156 / 415.6000061035156 | BULLISH | 409.1499938964844 | – | – | – | BULLISH | 409.1499938964844 |

#### chart_01/HV01 candles 26..44
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 26 | 3082.199951171875 / 3087.89990234375 / 3080.699951171875 / 3086.5 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 27 | 3086.5 / 3089.89990234375 / 3077.39990234375 / 3079.300048828125 | UNKNOWN | None | – | – | NO_ORIGIN_SWING | UNKNOWN | None |
| 28 | 3079.300048828125 / 3081.5 / 3076.0 / 3077.39990234375 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 29 | 3084.0 / 3092.89990234375 / 3083.60009765625 / 3089.5 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 30 | 3091.39990234375 / 3094.60009765625 / 3088.39990234375 / 3090.5 | UNKNOWN | None | STATE UNKNOWN->BULLISH [ESTABLISHED] | L@28=3076.0 | – | BULLISH | None |
| 31 | 3090.60009765625 / 3097.199951171875 / 3090.39990234375 / 3096.89990234375 | BULLISH | None | – | – | – | BULLISH | None |
| 32 | 3098.0 / 3099.0 / 3091.60009765625 / 3092.199951171875 | BULLISH | None | – | – | – | BULLISH | None |
| 33 | 3092.0 / 3096.60009765625 / 3091.89990234375 / 3096.300048828125 | BULLISH | None | – | – | – | BULLISH | None |
| 34 | 3096.0 / 3096.0 / 3092.0 / 3092.10009765625 | BULLISH | None | – | H@32=3099.0 | – | BULLISH | None |
| 35 | 3092.10009765625 / 3092.89990234375 / 3091.199951171875 / 3091.199951171875 | BULLISH | None | – | – | – | BULLISH | None |
| 36 | 3090.0 / 3094.0 / 3090.0 / 3093.199951171875 | BULLISH | None | – | – | – | BULLISH | None |
| 37 | 3095.699951171875 / 3095.699951171875 / 3083.10009765625 / 3085.60009765625 | BULLISH | None | – | – | – | BULLISH | None |
| 38 | 3084.60009765625 / 3087.10009765625 / 3079.39990234375 / 3079.39990234375 | BULLISH | None | – | – | – | BULLISH | None |
| 39 | 3079.5 / 3080.0 / 3075.89990234375 / 3077.10009765625 | BULLISH | None | – | H@37=3095.699951171875 | – | BULLISH | None |
| 40 | 3079.300048828125 / 3079.89990234375 / 3077.60009765625 / 3077.60009765625 | BULLISH | None | – | – | – | BULLISH | None |
| 41 | 3077.699951171875 / 3079.0 / 3073.300048828125 / 3076.60009765625 | BULLISH | None | – | – | – | BULLISH | None |
| 42 | 3076.60009765625 / 3076.60009765625 / 3072.60009765625 / 3072.699951171875 | BULLISH | None | BOS bearish vs 3076.0 | – | NOT_QUALIFIED(origin 3099.0 is not an LH (A5) (bos:bearish:swing:low:28:fi) | BULLISH | None |
| 43 | 3072.699951171875 / 3073.39990234375 / 3063.0 / 3065.39990234375 | BULLISH | None | – | – | – | BULLISH | None |
| 44 | 3065.199951171875 / 3065.800048828125 / 2971.300048828125 / 2972.10009765625 | BULLISH | None | – | – | – | BULLISH | None |

#### chart_05/HV05 candles 50..60
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 50 | 704.0499877929688 / 704.4000244140625 / 703.2999877929688 / 704.1500244140625 | BEARISH | 706.25 | – | – | – | BEARISH | 706.25 |
| 51 | 704.4000244140625 / 704.9000244140625 / 704.0 / 704.7000122070312 | BEARISH | 706.25 | – | – | – | BEARISH | 706.25 |
| 52 | 704.9000244140625 / 705.5999755859375 / 704.7000122070312 / 705.3499755859375 | BEARISH | 706.25 | – | L@50=703.2999877929688 | – | BEARISH | 706.25 |
| 53 | 705.5499877929688 / 707.9000244140625 / 705.5499877929688 / 707.5499877929688 | BEARISH | 706.25 | CHoCH bullish vs 706.25 (['high', '46']); STATE BEARISH->TRANSITION(bullish) [CHOCH]; BOS bullish vs 706.25 | – | NOT_QUALIFIED(origin 703.2999877929688 is not an HL (A5) (bos:bullish:swin) | TRANSITION(bullish) | None |
| 54 | 707.4500122070312 / 707.5 / 705.2000122070312 / 705.8499755859375 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 55 | 705.8499755859375 / 707.4500122070312 / 705.4500122070312 / 707.1500244140625 | TRANSITION(bullish) | None | – | H@53=707.9000244140625 | – | TRANSITION(bullish) | None |
| 56 | 707.1500244140625 / 707.2999877929688 / 706.3499755859375 / 706.4500122070312 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None |
| 57 | 706.4000244140625 / 707.5 / 705.8499755859375 / 706.6500244140625 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None |
| 58 | 706.5 / 707.0 / 705.0999755859375 / 706.3499755859375 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None |
| 59 | 706.3499755859375 / 707.4000244140625 / 705.9000244140625 / 706.4000244140625 | TRANSITION(bullish) | None | – | H@57=707.5 | – | TRANSITION(bullish) | None |
| 60 | 706.6500244140625 / 706.6500244140625 / 705.2999877929688 / 706.25 | TRANSITION(bullish) | None | – | L@58=705.0999755859375 | – | TRANSITION(bullish) | None |

#### EX04 candles 14..22
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 14 | 103.6428 / 104.3862 / 103.0461 / 103.3196 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 15 | 103.1944 / 104.5154 / 102.4753 / 103.9715 | UNKNOWN | None | BOS bullish vs 103.8411 | L@13=99.7595 | ACTIVATED(protected low 99.7595 activated at the close of index 15, in) | UNKNOWN | None |
| 16 | 104.5866 / 105.1723 / 101.9526 / 102.3851 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 17 | 102.6621 / 103.8542 / 101.8807 / 103.0792 | UNKNOWN | None | – | – | – | UNKNOWN | None |
| 18 | 103.1228 / 104.0252 / 98.829 / 99.3078 | UNKNOWN | None | STATE UNKNOWN->BULLISH [ESTABLISHED]; BOS bearish vs 99.7595 | H@16=105.1723 | NOT_QUALIFIED(origin 105.1723 is not an LH (A5) (bos:bearish:swing:low:13:); O9_UNRESOLVED(structure bullish established while close 99.3078 is already) | BULLISH | 99.7595 |
| 19 | 99.4939 / 100.4669 / 98.108 / 98.2218 | BULLISH | 99.7595 | CHoCH bearish vs 99.7595 (['low', '13']); STATE BULLISH->TRANSITION(bearish) [CHOCH] | – | – | TRANSITION(bearish) | None |
| 20 | 98.1796 / 100.4669 / 97.0667 / 97.1751 | TRANSITION(bearish) | None | – | – | – | TRANSITION(bearish) | None |
| 21 | 97.176 / 97.5976 / 96.3673 / 96.8753 | TRANSITION(bearish) | None | – | – | – | TRANSITION(bearish) | None |
| 22 | 97.2314 / 97.8234 / 96.2073 / 96.7652 | TRANSITION(bearish) | None | – | – | – | TRANSITION(bearish) | None |

#### chart_04/HV04 candles 56..66
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 56 | 10023.0 / 10042.0 / 10013.0 / 10039.0 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 57 | 10037.0 / 10039.0 / 10014.0 / 10016.0 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 58 | 10018.0 / 10037.0 / 10013.0 / 10030.0 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 59 | 10030.0 / 10040.0 / 10020.0 / 10040.0 | TRANSITION(bullish) | None | – | – | – | TRANSITION(bullish) | None |
| 60 | 10033.0 / 10033.0 / 9975.0 / 9983.0 | TRANSITION(bullish) | None | BOS bearish vs 10000.0 | – | O4_UNRESOLVED; O4_UNRESOLVED | TRANSITION(bullish) | None |
| 61 | 9983.0 / 9985.0 / 9969.0 / 9980.0 | TRANSITION(bullish) | None | – | H@59=10040.0 | O4_UNRESOLVED; ACTIVATED(protected high 10040.0 activated at the close of index 61, i) | TRANSITION(bullish) | None |
| 62 | 9984.0 / 10005.0 / 9971.0 / 10005.0 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 63 | 10007.0 / 10047.0 / 10007.0 / 10044.0 | TRANSITION(bullish) | None | STATE TRANSITION(bullish)->BULLISH [REVERSAL_CONFIRMED]; BOS bullish vs 10040.0 | L@61=9969.0 | NOT_QUALIFIED(origin 9969.0 is not an HL (A5) (bos:bullish:swing:high:59:f) | BULLISH | None |
| 64 | 10049.0 / 10066.0 / 10043.0 / 10048.0 | BULLISH | None | – | – | – | BULLISH | None |
| 65 | 10045.0 / 10050.0 / 10032.0 / 10049.0 | BULLISH | None | – | – | – | BULLISH | None |
| 66 | 10050.0 / 10050.0 / 10033.0 / 10040.0 | BULLISH | None | – | H@64=10066.0 | – | BULLISH | None |

#### chart_19/HV19 candles 43..54
| k | O / H / L / C | pre-state | pre-protected | events at close | swings confirmed | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|---|
| 43 | 1566.0 / 1566.199951171875 / 1565.300048828125 / 1565.300048828125 | BEARISH | 1567.5 | – | L@41=1562.5999755859375 | ACTIVATED(protected low 1562.5999755859375 activated at the close of i) | BEARISH | 1567.5 |
| 44 | 1565.300048828125 / 1567.0 / 1565.0 / 1567.0 | BEARISH | 1567.5 | – | – | – | BEARISH | 1567.5 |
| 45 | 1567.0 / 1568.0999755859375 / 1565.9000244140625 / 1567.300048828125 | BEARISH | 1567.5 | – | – | WICK_ONLY | BEARISH | 1567.5 |
| 46 | 1567.800048828125 / 1567.800048828125 / 1566.0999755859375 / 1567.300048828125 | BEARISH | 1567.5 | – | – | WICK_ONLY | BEARISH | 1567.5 |
| 47 | 1567.4000244140625 / 1567.9000244140625 / 1566.4000244140625 / 1567.0 | BEARISH | 1567.5 | – | H@45=1568.0999755859375 | WICK_ONLY | BEARISH | 1567.5 |
| 48 | 1567.5999755859375 / 1567.5999755859375 / 1566.300048828125 / 1566.4000244140625 | BEARISH | 1567.5 | – | – | WICK_ONLY | BEARISH | 1567.5 |
| 49 | 1566.4000244140625 / 1566.9000244140625 / 1566.300048828125 / 1566.9000244140625 | BEARISH | 1567.5 | – | – | – | BEARISH | 1567.5 |
| 50 | 1566.9000244140625 / 1568.5 / 1566.5 / 1568.0 | BEARISH | 1567.5 | CHoCH bullish vs 1567.5 (['high', '32']); STATE BEARISH->TRANSITION(bullish) [CHOCH] | – | – | TRANSITION(bullish) | None |
| 51 | 1568.199951171875 / 1568.5 / 1566.9000244140625 / 1566.9000244140625 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 52 | 1567.4000244140625 / 1568.199951171875 / 1566.4000244140625 / 1567.300048828125 | TRANSITION(bullish) | None | – | – | O4_UNRESOLVED | TRANSITION(bullish) | None |
| 53 | 1567.4000244140625 / 1570.5 / 1567.0999755859375 / 1569.9000244140625 | TRANSITION(bullish) | None | STATE TRANSITION(bullish)->BULLISH [REVERSAL_CONFIRMED]; BOS bullish vs 1568.0999755859375 | – | – | BULLISH | None |
| 54 | 1570.0 / 1572.5 / 1569.9000244140625 / 1572.4000244140625 | BULLISH | None | – | L@52=1566.4000244140625 | ACTIVATED(protected low 1566.4000244140625 activated at the close of i) | BULLISH | 1566.4000244140625 |

# Appendix B — Minimal CHU04 equality cases (built in memory from CHD01 c1–c17)

#### E1 bullish structure: close == protected 101 (c17), later close 100.5 < 101 (c19)
| k | O/H/L/C | pre-state | pre-protected | events | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|
| 14 | 115.0/115.0/110.0/111.0 | UNKNOWN | None | – | – | UNKNOWN | None |
| 15 | 111.0/112.0/106.0/107.0 | UNKNOWN | None | STATE UNKNOWN->BULLISH [ESTABLISHED] | – | BULLISH | 101.0 |
| 16 | 107.0/108.0/103.0/104.0 | BULLISH | 101.0 | – | – | BULLISH | 101.0 |
| 17 | 103.0/104.0/100.0/101.0 | BULLISH | 101.0 | – | EXACT_LEVEL_CLOSE | BULLISH | 101.0 |
| 18 | 101.0/102.0/100.2/101.5 | BULLISH | 101.0 | – | WICK_ONLY | BULLISH | 101.0 |
| 19 | 101.5/101.8/100.0/100.5 | BULLISH | 101.0 | CHoCH bearish vs 101.0 (id low@9); STATE BULLISH->TRANSITION(bearish) [CHOCH]; BOS bearish vs 101.0 | NOT_QUALIFIED | TRANSITION(bearish) | None |

#### E2 mirror (bearish structure): close == protected 99, later close 99.5 > 99
| k | O/H/L/C | pre-state | pre-protected | events | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|
| 14 | 85.0/90.0/85.0/89.0 | UNKNOWN | None | – | – | UNKNOWN | None |
| 15 | 89.0/94.0/88.0/93.0 | UNKNOWN | None | STATE UNKNOWN->BEARISH [ESTABLISHED] | – | BEARISH | 99.0 |
| 16 | 93.0/97.0/92.0/96.0 | BEARISH | 99.0 | – | – | BEARISH | 99.0 |
| 17 | 97.0/100.0/96.0/99.0 | BEARISH | 99.0 | – | EXACT_LEVEL_CLOSE | BEARISH | 99.0 |
| 18 | 99.0/99.8/98.0/98.5 | BEARISH | 99.0 | – | WICK_ONLY | BEARISH | 99.0 |
| 19 | 98.5/100.0/98.2/99.5 | BEARISH | 99.0 | CHoCH bullish vs 99.0 (id high@9); STATE BEARISH->TRANSITION(bullish) [CHOCH]; BOS bullish vs 99.0 | NOT_QUALIFIED | TRANSITION(bullish) | None |

#### E3 two equality closes, never beyond
| k | O/H/L/C | pre-state | pre-protected | events | diagnostics | state after | protected for k+1 |
|---|---|---|---|---|---|---|---|
| 14 | 115.0/115.0/110.0/111.0 | UNKNOWN | None | – | – | UNKNOWN | None |
| 15 | 111.0/112.0/106.0/107.0 | UNKNOWN | None | STATE UNKNOWN->BULLISH [ESTABLISHED] | – | BULLISH | 101.0 |
| 16 | 107.0/108.0/103.0/104.0 | BULLISH | 101.0 | – | – | BULLISH | 101.0 |
| 17 | 103.0/104.0/100.0/101.0 | BULLISH | 101.0 | – | EXACT_LEVEL_CLOSE | BULLISH | 101.0 |
| 18 | 101.0/103.0/100.5/101.0 | BULLISH | 101.0 | – | EXACT_LEVEL_CLOSE | BULLISH | 101.0 |
| 19 | 101.0/104.0/101.0/103.0 | BULLISH | 101.0 | – | – | BULLISH | 101.0 |

