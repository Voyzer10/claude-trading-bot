import numpy as np, json, sys, os
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calib import calibrate

def classify(px):
    r, g, b = px
    if g - r > 50: return 'G'        # green fill
    if r - g > 80: return 'R'        # red fill
    lum = (r + g + b) / 3
    if lum < 120:
        if g > r + 3: return 'g'     # green edge
        if r > g + 3: return 'r'     # red edge
        return 'k'                   # wick
    return None

def extract(path):
    c = calibrate(path)
    a = np.array(Image.open(path).convert('RGB')).astype(int)
    T, B, L, R = c['T'], c['B'], c['L'], c['R']
    lum = a.mean(2)
    price = lambda y: float(np.polyval(c['py'], y))
    cands = []
    i = 0
    while True:
        cx = np.polyval(c['px'], i)
        if cx > R - 3: break
        xc = int(round(cx))
        # wick column: darkest column near centre
        best = None
        for x in (xc - 1, xc, xc + 1):
            col = lum[T + 1:B, x]
            n = (col < 120).sum()
            if best is None or n > best[0]: best = (n, x)
        xw = best[1]
        col = lum[T + 1:B, xw]
        rows = np.where(col < 170)[0] + T + 1
        if len(rows) == 0:
            if cx < L + 3: i += 1; continue
            break
        top, bot = rows.min(), rows.max()
        # body: columns offset from wick
        brows = []; kinds = []
        for x in (xw - 3, xw + 3, xw - 2, xw + 2):
            for y in range(top, bot + 1):
                k = classify(a[y, x])
                if k: brows.append(y); kinds.append(k)
        if not brows:
            bt = bb = (top + bot) / 2; colr = '?'
        else:
            bt, bb = min(brows), max(brows)
            nG = kinds.count('G') + 0.1 * kinds.count('g'); nR = kinds.count('R') + 0.1 * kinds.count('r')
            colr = 'G' if nG >= nR else 'R'
        hi, lo = price(top), price(bot)
        btp, bbp = price(bt), price(bb)
        if colr == 'G': o, cl = bbp, btp
        else: o, cl = btp, bbp
        if bb - bt <= 1: o = cl = (btp + bbp) / 2
        cands.append(dict(i=i, x=float(cx), o=round(o, 4), h=round(hi, 4), l=round(lo, 4), c=round(cl, 4),
                          ytop=int(top), ybot=int(bot), ybt=int(bt), ybb=int(bb), color=colr))
        i += 1
    return c, cands

if __name__ == '__main__':
    c, cs = extract(sys.argv[1])
    print(len(cs), 'px/price', 1 / abs(c['py'][0]))
    for d in cs[:12]: print(d)
