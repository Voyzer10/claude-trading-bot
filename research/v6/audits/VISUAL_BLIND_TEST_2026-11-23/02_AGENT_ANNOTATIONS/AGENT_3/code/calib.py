import numpy as np, subprocess, os, re, sys, tempfile
from PIL import Image

def frame(a):
    blk = (a.sum(2) == 0)
    r = blk.sum(1); c = blk.sum(0)
    rows = [i for i in range(a.shape[0]) if r[i] > 500]
    cols = [i for i in range(a.shape[1]) if c[i] > 300]
    return rows[0], rows[-1], cols[0], cols[-1], blk

def ocr(img, psm=7, wl='0123456789.-'):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'x.png'); img.save(p)
        out = subprocess.run(['tesseract', p, 'stdout', '--psm', str(psm), '-c', 'tessedit_char_whitelist=' + wl],
                             capture_output=True, text=True).stdout
    return out.strip()

def calibrate(path):
    im = Image.open(path).convert('RGB'); a = np.array(im).astype(int)
    T, B, L, R, blk = frame(a)
    yt = [y for y in range(T, B + 1) if blk[y, L - 3]]
    xt = [x for x in range(L, R + 1) if blk[B + 3, x]]
    g = im.convert('L')
    ylab = []
    for y in yt:
        crop = g.crop((0, y - 9, L - 5, y + 9)).resize(((L - 5) * 4, 72), Image.LANCZOS)
        t = ocr(crop)
        try: ylab.append((y, float(t)))
        except: pass
    xlab = []
    for x in xt:
        crop = g.crop((x - 25, B + 6, x + 25, B + 26)).resize((200, 80), Image.LANCZOS)
        t = ocr(crop, wl='0123456789')
        try: xlab.append((x, float(t)))
        except: pass
    from collections import Counter
    def robust(lab, allt):
        lab = np.array(lab); idx = {t: k for k, t in enumerate(allt)}
        k = np.array([idx[int(p)] for p in lab[:, 0]])
        d = [round((lab[j+1,1]-lab[j,1])/(k[j+1]-k[j]), 6) for j in range(len(lab)-1)]
        step = Counter(d).most_common(1)[0][0]
        off = Counter([round(v - kk*step, 6) for v, kk in zip(lab[:,1], k)]).most_common(1)[0][0]
        good = np.abs(lab[:,1] - (off + k*step)) < 1e-6
        return np.array([(allt[j], off + j*step) for j in range(len(allt))]), int((~good).sum())
    ys, ybad = robust(ylab, yt); xs, xbad = robust(xlab, xt)
    py = np.polyfit(ys[:, 0], ys[:, 1], 1)   # price = py[0]*y + py[1]
    px = np.polyfit(xs[:, 1], xs[:, 0], 1)   # pixel_x = px[0]*idx + px[1]
    ry = ys[:, 1] - np.polyval(py, ys[:, 0]); rx = xs[:, 0] - np.polyval(px, xs[:, 1])
    return dict(T=T, B=B, L=L, R=R, py=py, px=px, ylab=ylab, xlab=xlab,
                ybad=ybad, xbad=xbad, yres=float(np.abs(ry).max()), xres=float(np.abs(rx).max()))

if __name__ == '__main__':
    c = calibrate(sys.argv[1])
    print({k: v for k, v in c.items()})
