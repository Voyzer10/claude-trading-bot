import numpy as np, json, sys, os, csv, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
from extract import extract

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
IN = os.path.abspath(os.path.join(OUT, '..', 'input', 'charts'))
FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)

def conf_from_margin(m, base=0.9):
    # m = pixel margin of the decisive comparison
    if m >= 4: return base
    if m == 3: return round(base - 0.1, 2)
    if m == 2: return round(base - 0.2, 2)
    return round(base - 0.4, 2)

def analyse(cs, price):
    n = len(cs)
    H = [d['ytop'] for d in cs]; Lw = [d['ybot'] for d in cs]   # rows (smaller row = higher price)
    C = [d['ybt'] if d['color'] == 'G' else d['ybb'] for d in cs]  # close row
    if True:
        for k, d in enumerate(cs):
            if d['ybb'] - d['ybt'] <= 1: C[k] = (d['ybt'] + d['ybb']) / 2
    ev = []
    sh, sl = [], []   # swings: dict(i, row, margin)
    for i in range(2, n - 2):
        nb = [H[i - 2], H[i - 1], H[i + 1], H[i + 2]]
        if all(H[i] < x for x in nb):
            sh.append(dict(i=i, row=H[i], m=min(nb) - H[i]))
        nb = [Lw[i - 2], Lw[i - 1], Lw[i + 1], Lw[i + 2]]
        if all(Lw[i] > x for x in nb):
            sl.append(dict(i=i, row=Lw[i], m=Lw[i] - max(nb)))
    for s in sh:
        ev.append(dict(type='POOL_BSL', candle_index=s['i'], price=round(price(s['row']), 2),
                       confidence=conf_from_margin(s['m'], 0.9), note=f"swing high, margin {s['m']}px"))
    for s in sl:
        ev.append(dict(type='POOL_SSL', candle_index=s['i'], price=round(price(s['row']), 2),
                       confidence=conf_from_margin(s['m'], 0.9), note=f"swing low, margin {s['m']}px"))
    # liquidity: sweeps / takes; pool consumed on first sweep or take
    for s in sh:
        for j in range(s['i'] + 3, n):
            if H[j] < s['row']:
                if C[j] >= s['row']:
                    m = min(s['row'] - H[j], C[j] - s['row'] + 1)
                    ev.append(dict(type='SWEEP_BSL', candle_index=j, price=round(price(s['row']), 2),
                                   confidence=min(conf_from_margin(m, 0.8), conf_from_margin(s['m'], 0.8)),
                                   note=f"swept pool of candle {s['i']}"))
                else:
                    ev.append(dict(type='TAKEN_BSL', candle_index=j, price=round(price(s['row']), 2),
                                   confidence=min(conf_from_margin(s['row'] - C[j], 0.7), conf_from_margin(s['m'], 0.7)),
                                   note=f"close above pool of candle {s['i']}"))
                break
    for s in sl:
        for j in range(s['i'] + 3, n):
            if Lw[j] > s['row']:
                if C[j] <= s['row']:
                    m = min(Lw[j] - s['row'], s['row'] - C[j] + 1)
                    ev.append(dict(type='SWEEP_SSL', candle_index=j, price=round(price(s['row']), 2),
                                   confidence=min(conf_from_margin(m, 0.8), conf_from_margin(s['m'], 0.8)),
                                   note=f"swept pool of candle {s['i']}"))
                else:
                    ev.append(dict(type='TAKEN_SSL', candle_index=j, price=round(price(s['row']), 2),
                                   confidence=min(conf_from_margin(C[j] - s['row'], 0.7), conf_from_margin(s['m'], 0.7)),
                                   note=f"close below pool of candle {s['i']}"))
                break
    # structure: BOS / CHOCH  (trend state machine)
    # state is first set when the known swings show HH+HL (up) or LH+LL (down); afterwards a CHoCH flips it.
    # protected level: up -> swing low that started the leg of the last bullish break (most recent known swing low
    # before that break candle); fallback before any break: swing low preceding the highest known swing high.
    broken = set(); choch_used = set()
    state = None; prot = None
    for j in range(n):
        kh = [s for s in sh if s['i'] + 2 < j]
        kl = [s for s in sl if s['i'] + 2 < j]
        if state is not None and (prot is None or (('L' if state == 'up' else 'H'), prot['i']) in broken):
            state = None   # protected level gone without a CHoCH (e.g. broken before the trend was established)
        if state is None and len(kh) >= 2 and len(kl) >= 2:
            if kh[-1]['row'] < kh[-2]['row'] and kl[-1]['row'] < kl[-2]['row']:
                state = 'up'; top = min(kh, key=lambda s: (s['row'], -s['i']))
                c_ = [s for s in kl if s['i'] < top['i']]; prot = c_[-1] if c_ else None
                if prot is None or ('L', prot['i']) in broken: state = None; prot = None
            elif kh[-1]['row'] > kh[-2]['row'] and kl[-1]['row'] > kl[-2]['row']:
                state = 'down'; bot = max(kl, key=lambda s: (s['row'], s['i']))
                c_ = [s for s in kh if s['i'] < bot['i']]; prot = c_[-1] if c_ else None
                if prot is None or ('H', prot['i']) in broken: state = None; prot = None
        done_bull = done_bear = False
        if state == 'up' and prot is not None and ('L', prot['i']) not in broken and C[j] > prot['row']:
            p = prot; choch_used.add(('L', p['i'])); broken.add(('L', p['i']))
            ev.append(dict(type='CHOCH', direction='bearish', candle_index=j, price=round(price(p['row']), 2),
                           confidence=min(conf_from_margin(C[j] - p['row'], 0.55), 0.55),
                           note=f"uptrend protected low of candle {p['i']} closed below"))
            done_bear = True; state = 'down'
            c_ = [s for s in sh if s['i'] + 2 <= j]; prot = c_[-1] if c_ else None
        elif state == 'down' and prot is not None and ('H', prot['i']) not in broken and C[j] < prot['row']:
            p = prot; choch_used.add(('H', p['i'])); broken.add(('H', p['i']))
            ev.append(dict(type='CHOCH', direction='bullish', candle_index=j, price=round(price(p['row']), 2),
                           confidence=min(conf_from_margin(p['row'] - C[j], 0.55), 0.55),
                           note=f"downtrend protected high of candle {p['i']} closed above"))
            done_bull = True; state = 'up'
            c_ = [s for s in sl if s['i'] + 2 <= j]; prot = c_[-1] if c_ else None
        if kh and not done_bull:
            s = kh[-1]
            if ('H', s['i']) not in broken and C[j] < s['row']:
                broken.add(('H', s['i']))
                ev.append(dict(type='BOS', direction='bullish', candle_index=j, price=round(price(s['row']), 2),
                               confidence=min(conf_from_margin(s['row'] - C[j], 0.85), conf_from_margin(s['m'], 0.85)),
                               note=f"close above swing high of candle {s['i']}" + (f" (state {state})" if state else "")))
                if state == 'up':
                    c_ = [x for x in sl if x['i'] + 2 <= j]; prot = c_[-1] if c_ else prot
        if kl and not done_bear:
            s = kl[-1]
            if ('L', s['i']) not in broken and C[j] > s['row']:
                broken.add(('L', s['i']))
                ev.append(dict(type='BOS', direction='bearish', candle_index=j, price=round(price(s['row']), 2),
                               confidence=min(conf_from_margin(C[j] - s['row'], 0.85), conf_from_margin(s['m'], 0.85)),
                               note=f"close below swing low of candle {s['i']}" + (f" (state {state})" if state else "")))
                if state == 'down':
                    c_ = [x for x in sh if x['i'] + 2 <= j]; prot = c_[-1] if c_ else prot
    order = ['BOS', 'CHOCH', 'POOL_BSL', 'POOL_SSL', 'SWEEP_BSL', 'SWEEP_SSL', 'TAKEN_BSL', 'TAKEN_SSL']
    ev.sort(key=lambda e: (e['candle_index'], order.index(e['type'])))
    return ev, sh, sl

def draw(path, out, ev, cs, calib):
    im = Image.open(path).convert('RGB'); d = ImageDraw.Draw(im)
    py = calib['py']
    yof = lambda p: (p - py[1]) / py[0]
    xof = lambda i: float(np.polyval(calib['px'], i))
    for e in ev:
        t = e['type']; i = e['candle_index']; y = yof(e['price']); x = xof(i)
        src = None
        if 'note' in e:
            import re
            m = re.search(r'candle (\d+)', e['note'])
            if m: src = int(m.group(1))
        if t == 'POOL_BSL':
            d.line([(x - 8, y), (x + 8, y)], fill=(255, 140, 0), width=3)
        elif t == 'POOL_SSL':
            d.line([(x - 8, y), (x + 8, y)], fill=(0, 150, 150), width=3)
        elif t in ('BOS', 'CHOCH'):
            col = (30, 90, 230) if t == 'BOS' else (150, 40, 200)
            x0 = xof(src) if src is not None else x - 40
            d.line([(x0, y), (x, y)], fill=col, width=2)
            up = e['direction'] == 'bullish'
            lab = ('BOS' if t == 'BOS' else 'CHoCH') + ('↑' if up else '↓')
            d.text((x + 3, y - 16 if up else y + 3), lab, fill=col, font=FONT)
        elif t.startswith('SWEEP'):
            c = cs[i]
            yy = c['ytop'] if t == 'SWEEP_BSL' else c['ybot']
            col = (230, 0, 120)
            d.ellipse([(x - 7, yy - 7), (x + 7, yy + 7)], outline=col, width=2)
            x0 = xof(src) if src is not None else x - 30
            for xx in np.arange(x0, x, 6): d.line([(xx, y), (min(xx + 3, x), y)], fill=col, width=1)
            d.text((x + 8, yy - 20 if t == 'SWEEP_BSL' else yy + 6), 'SW-BSL' if t == 'SWEEP_BSL' else 'SW-SSL', fill=col, font=FONT)
        elif t.startswith('TAKEN'):
            col = (120, 120, 120)
            d.text((x - 4, y - 14 if t == 'TAKEN_BSL' else y + 2), 'T', fill=col, font=FONT)
    im.save(out)

def main():
    rows = []
    summary = {}
    for p in sorted(glob.glob(os.path.join(IN, '*', '*.png'))):
        cid = os.path.basename(p)[:-4]
        calib, cs = extract(p)
        price = lambda r: float(np.polyval(calib['py'], r))
        ev, sh, sl = analyse(cs, price)
        js = dict(chart_id=cid, agent='AGENT_3',
                  method='pixel analysis (PIL/numpy): axes calibrated from OCR of tick labels + tick-mark pixels; '
                         'per-candle OHLC from wick/body pixel rows; README definitions applied in code on pixel rows; '
                         'confidence lowered when decisive comparison margin is <=2 px',
                  events=[{k: v for k, v in e.items()} for e in ev])
        json.dump(js, open(os.path.join(OUT, cid + '.json'), 'w'), indent=1, ensure_ascii=False)
        json.dump(dict(calib={k: (v.tolist() if hasattr(v, 'tolist') else v) for k, v in calib.items()}, candles=cs),
                  open(os.path.join(OUT, 'code', 'ohlc_' + cid + '.json'), 'w'))
        draw(p, os.path.join(OUT, cid + '_marked.png'), ev, cs, calib)
        for e in ev:
            rows.append([cid, e['type'], e.get('direction', ''), e['candle_index'], f"{e['price']:.2f}", e['confidence'], e['note']])
        from collections import Counter
        summary[cid] = (len(cs), 1 / abs(calib['py'][0]), calib['ybad'], dict(Counter(e['type'] for e in ev)))
    with open(os.path.join(OUT, 'annotations_all.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['chart_id', 'type', 'direction', 'candle_index', 'price', 'confidence', 'note']); w.writerows(rows)
    for k, v in summary.items(): print(k, v)

if __name__ == '__main__':
    main()
