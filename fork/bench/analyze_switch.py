"""Analyze sim_switch.py output: where do pieces start to pay off?

    python3 analyze_switch.py switch.jsonl [REAL_LENGTHS.txt]

REAL_LENGTHS.txt (optional): one dictation length in seconds per line, e.g. from the
gateway's debug log (`audio=...ms`). Used to weight the modes by how long real
dictations are.

Prints, by length band: wrong words and model wait for the whole recording, plain pieces
and each switch point T; the paired accuracy difference pieces - whole fitted against
length (where it crosses zero); and, per T, wrong words and mean wait over the real
length mix.
"""
import json, math, sys
from collections import defaultdict

BANDS = [(0, 15), (15, 25), (25, 40), (40, 60), (60, 90), (90, 130)]


def band(L):
    for a, b in BANDS:
        if a <= L < b:
            return (a, b)


def fit_line(xs, ys, ws):
    sw = sum(ws); mx = sum(w * x for w, x in zip(ws, xs)) / sw; my = sum(w * y for w, y in zip(ws, ys)) / sw
    sxx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs)); sxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def main():
    rows = [json.loads(l) for l in open(sys.argv[1])]
    real = [float(x) for x in open(sys.argv[2])] if len(sys.argv) > 2 else []
    pts = defaultdict(dict)                      # (clip, len) -> mode -> row
    for r in rows:
        pts[(r["clip"], r["len"])][r["mode"]] = r
    modes = ["whole"] + sorted({r["mode"] for r in rows} - {"whole"}, key=lambda m: int(m[1:]))

    print("Wrong words % / model wait s, by dictation length")
    print(f"{'length':<10}{'n':>4}" + "".join(f"{m:>14}" for m in modes))
    for bd in BANDS:
        ks = [k for k in pts if band(k[1]) == bd]
        if not ks:
            continue
        cells = []
        for m in modes:
            e = sum(pts[k][m]["err"] for k in ks); n = sum(pts[k][m]["ref_words"] for k in ks)
            w = sum(pts[k][m]["wait"] for k in ks) / len(ks)
            cells.append(f"{e / n * 100:5.1f}% {w:5.2f}s")
        print(f"{bd[0]:>3}-{bd[1]:<4}s{len(ks):>5}" + "".join(f"{c:>14}" for c in cells))

    # Paired accuracy difference, plain pieces (T8) minus whole, per word, against log length.
    xs, ys, ws = [], [], []
    for k, d in pts.items():
        n = d["whole"]["ref_words"]
        xs.append(math.log(k[1])); ys.append((d["T8"]["err"] - d["whole"]["err"]) / n * 100); ws.append(n)
    a, b = fit_line(xs, ys, ws)
    cross = math.exp(-a / b) if b < 0 else float("inf")
    print(f"\nPieces minus whole, wrong-word points = {a:.2f} {b:+.2f}*ln(length s); zero at {cross:.0f} s")
    # bootstrap the crossover by clip
    import random
    clips = sorted({k[0] for k in pts}); rnd = random.Random(1); cs = []
    for _ in range(2000):
        pick = [rnd.choice(clips) for _ in clips]
        bx, by, bw = [], [], []
        for c in pick:
            for k, d in pts.items():
                if k[0] == c:
                    n = d["whole"]["ref_words"]
                    bx.append(math.log(k[1])); by.append((d["T8"]["err"] - d["whole"]["err"]) / n * 100); bw.append(n)
        try:
            ba, bb = fit_line(bx, by, bw)
        except ZeroDivisionError:
            continue
        if bb < 0:
            cs.append(math.exp(-ba / bb))
    cs.sort()
    if cs:
        print(f"  crossover 80% interval (bootstrap over clips): {cs[len(cs) // 10]:.0f}-{cs[len(cs) * 9 // 10]:.0f} s")

    # Whole-recording model wait against length: wait = c0 + c1*L + c2*L^2 (least squares).
    L = [k[1] for k in pts]; W = [pts[k]["whole"]["wait"] for k in pts]
    X = [[1, l, l * l] for l in L]
    XtX = [[sum(x[i] * x[j] for x in X) for j in range(3)] for i in range(3)]
    XtY = [sum(x[i] * w for x, w in zip(X, W)) for i in range(3)]
    c = solve(XtX, XtY)
    print(f"Whole-recording model wait = {c[0]:.2f} + {c[1]:.4f}*L + {c[2]:.6f}*L^2 s")
    for t in (1.0, 2.0):
        l = next((l for l in range(1, 200) if c[0] + c[1] * l + c[2] * l * l > t), None)
        print(f"  passes {t:.0f} s at about {l} s of speech")

    if real:
        # Weight every simulated point so the length bands match the real mix.
        share = defaultdict(float)
        for x in real:
            bd = band(min(x, 129))
            if bd:
                share[bd] += 1 / len(real)
        nb = defaultdict(int)
        for k in pts:
            nb[band(k[1])] += 1
        print(f"\nOver the given length mix ({len(real)} dictations; share by band: "
              + ", ".join(f"{a}-{b}s {share[(a, b)] * 100:.0f}%" for a, b in BANDS) + ")")
        print(f"{'mode':<8}{'wrong words':>13}{'mean wait':>11}{'worst band wait':>17}")
        for m in modes:
            e = n = w = 0.0; worst = 0.0
            for bd in BANDS:
                ks = [k for k in pts if band(k[1]) == bd]
                if not ks or not share[bd]:
                    continue
                be = sum(pts[k][m]["err"] for k in ks) / sum(pts[k][m]["ref_words"] for k in ks)
                bw = sum(pts[k][m]["wait"] for k in ks) / len(ks)
                words = (bd[0] + bd[1]) / 2 * 2.5          # words scale with length
                e += share[bd] * be * words; n += share[bd] * words; w += share[bd] * bw
                worst = max(worst, bw)
            print(f"{m:<8}{e / n * 100:>12.2f}%{w:>10.2f}s{worst:>16.2f}s")


def solve(A, y):
    n = len(y); M = [row[:] + [y[i]] for i, row in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i])); M[i], M[p] = M[p], M[i]
        for r in range(n):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [a - f * b for a, b in zip(M[r], M[i])]
    return [M[i][n] / M[i][i] for i in range(n)]


if __name__ == "__main__":
    main()
