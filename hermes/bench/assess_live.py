"""Assess the live trial from the gateway's debug log: is the switch paying off on real use?

    python3 assess_live.py TRIAL_START LOG [LOG ...]

TRIAL_START is when the setting under test went live (ISO time, e.g. 2026-11-09T14:12:56-07:00).
LOG files are journal lines (`journalctl -o short-iso`) of the diction-gateway and
speech-gateway units, filtered to the metric lines: `ws debug:`, `live:`, `ws proxy:` and
`fuzzy:` (hermes/trial/collect.sh does this). These lines hold timings, lengths and counts
only, never transcript text; this script prints aggregates only.

It compares dictations from TRIAL_START on with the whole-recording dictations before it:
  - wait after release (done_to_text) by length band, median / 90th percentile / worst;
  - time saved per dictation against a quadratic fit of the baseline's wait vs length;
  - how the trial dictations were served (whole under the switch point, pieces, fallback);
  - piece failures, backend errors, lookup-table swaps;
  - characters per second of audio, a rough check that pieces do not drop words.
It cannot measure wrong words: the log has no reference text.
"""
import re, sys
from datetime import datetime
from statistics import median

BANDS = [(0, 15), (15, 25), (25, 40), (40, 60), (60, 90), (90, 600)]
TS = re.compile(r"^(\S+)\s")


def band(sec):
    for a, b in BANDS:
        if a <= sec < b:
            return (a, b)


def label(bd):
    return f"{bd[0]}-{bd[1]} s" if bd[1] < 600 else f"{bd[0]}+ s"


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def parse(paths):
    """Yield one dict per finished dictation, in time order."""
    lines = []
    for p in paths:
        for ln in open(p, encoding="utf-8", errors="replace"):
            m = TS.match(ln)
            if m:
                try:
                    lines.append((datetime.fromisoformat(m.group(1)), ln))
                except ValueError:
                    pass
    lines.sort(key=lambda x: x[0])
    cur, swaps_pending = None, 0
    for t, ln in lines:
        if "fuzzy:" in ln:
            # The speech gateway logs the swap before the Diction gateway logs done_to_text.
            if cur is not None:
                cur["swaps"] += 1
            else:
                swaps_pending += 1
            continue
        if "ws debug: open" in ln:
            cur = {"t": t, "mode": "whole", "pieces": 0, "fail": 0, "err": 0, "swaps": swaps_pending,
                   "fallback": False, "final_wait": None}
            swaps_pending = 0
            continue
        if cur is None:
            continue
        if "live: segment failed" in ln:
            cur["fail"] += 1
        elif "live: decode incomplete" in ln:
            cur["fallback"] = True
        elif "ws proxy:" in ln:
            cur["err"] += 1
        elif "live: final" in ln:
            m = re.search(r"ok=(\w+) segments=(\d+).*?wait=(\d+)ms", ln)
            if m:
                ok, segs = m.group(1) == "true", int(m.group(2))
                cur["pieces"] = segs
                cur["final_wait"] = int(m.group(3))
                cur["mode"] = "pieces" if ok and segs > 0 else ("whole (under switch)" if ok else "fallback")
        elif "ws debug: done_to_text" in ln:
            m = re.search(r"done_to_text=(\d+)ms stt=(\d+)ms audio=(\d+)ms chars=(\d+)", ln)
            if m:
                cur.update(wait=int(m.group(1)) / 1000, stt=int(m.group(2)) / 1000,
                           audio=int(m.group(3)) / 1000, chars=int(m.group(4)))
                if cur["fallback"]:
                    cur["mode"] = "fallback"
                if cur["audio"] > 0.5:
                    yield cur
            cur = None


def fit_quadratic(L, W):
    X = [[1, l, l * l] for l in L]
    A = [[sum(x[i] * x[j] for x in X) for j in range(3)] for i in range(3)]
    y = [sum(x[i] * w for x, w in zip(X, W)) for i in range(3)]
    n = 3; M = [A[i][:] + [y[i]] for i in range(n)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i])); M[i], M[p] = M[p], M[i]
        for r in range(n):
            if r != i:
                f = M[r][i] / M[i][i]; M[r] = [a - f * b for a, b in zip(M[r], M[i])]
    return [M[i][n] / M[i][i] for i in range(n)]


def table(title, groups):
    print(f"\n{title}")
    print(f"{'length':<10}" + "".join(f"{name:>30}" for name in groups))
    for bd in BANDS:
        cells = []
        for rows in groups.values():
            ws = [d["wait"] for d in rows if band(d["audio"]) == bd]
            cells.append(f"n={len(ws):<3} {median(ws):5.2f} / {pct(ws, 90):5.2f} / {max(ws):5.2f}" if ws else "-")
        print(f"{label(bd):<10}" + "".join(f"{c:>30}" for c in cells))


def main():
    start = datetime.fromisoformat(sys.argv[1])
    ds = list(parse(sys.argv[2:]))
    base = [d for d in ds if d["t"] < start and d["mode"] == "whole"]
    trial = [d for d in ds if d["t"] >= start]
    if not trial:
        print(f"No dictations since {start.isoformat()} yet ({len(base)} baseline).")
        return
    days = max(1e-9, (trial[-1]["t"] - trial[0]["t"]).total_seconds() / 86400)
    print(f"Baseline (whole recording, before {start:%Y-%m-%d %H:%M}): {len(base)} dictations")
    print(f"Trial: {len(trial)} dictations over {days:.1f} days, "
          f"{sum(d['audio'] for d in trial) / 60:.0f} min of speech")

    print("\nLength mix (share of dictations)")
    for bd in BANDS:
        b = sum(band(d["audio"]) == bd for d in base) / max(1, len(base))
        t = sum(band(d["audio"]) == bd for d in trial) / len(trial)
        print(f"  {label(bd):<10} baseline {b * 100:4.0f}%   trial {t * 100:4.0f}%")

    table("Wait after release, s (median / 90th pct / worst)", {"baseline (whole)": base, "trial": trial})

    if len(base) >= 8:
        c = fit_quadratic([d["audio"] for d in base], [d["wait"] for d in base])
        pred = lambda L: c[0] + c[1] * L + c[2] * L * L
        print(f"\nBaseline fit: wait = {c[0]:.2f} + {c[1]:.4f}*L + {c[2]:.6f}*L^2 s "
              f"(fitted on {min(d['audio'] for d in base):.0f}-{max(d['audio'] for d in base):.0f} s)")
        for name, rows in (("all trial dictations", trial),
                           ("15 s and longer", [d for d in trial if d["audio"] >= 15])):
            if rows:
                saved = [pred(d["audio"]) - d["wait"] for d in rows]
                print(f"  {name:<22} predicted whole {sum(pred(d['audio']) for d in rows) / len(rows):5.2f} s, "
                      f"actual {sum(d['wait'] for d in rows) / len(rows):5.2f} s, "
                      f"saved {sum(saved) / len(saved):+5.2f} s per dictation ({sum(saved) / 60:.1f} min in all)")

    print("\nHow trial dictations were served")
    for mode in ("whole (under switch)", "pieces", "whole", "fallback"):
        rows = [d for d in trial if d["mode"] == mode]
        if rows:
            extra = ""
            if mode == "pieces":
                extra = (f", {sum(d['pieces'] for d in rows) / len(rows):.1f} pieces each, "
                         f"final wait on pieces {median([d['final_wait'] for d in rows]) / 1000:.2f} s median")
            print(f"  {mode:<22} {len(rows):>4} ({len(rows) / len(trial) * 100:3.0f}%), "
                  f"{min(d['audio'] for d in rows):.0f}-{max(d['audio'] for d in rows):.0f} s{extra}")
    over = [d for d in trial if d["audio"] >= 16 and d["mode"] != "pieces"]
    if over:
        print(f"  note: {len(over)} dictations of 16 s or more were not served in pieces "
              f"(no pause after 15 s, or a fallback)")

    print("\nProblems (trial)")
    print(f"  piece failures {sum(d['fail'] for d in trial)}, fallbacks to whole {sum(d['fallback'] for d in trial)}, "
          f"backend errors {sum(d['err'] for d in trial)}")
    print(f"  lookup-table swaps {sum(d['swaps'] for d in trial)} "
          f"({sum(d['swaps'] for d in trial) / len(trial):.2f} per dictation; "
          f"baseline {sum(d['swaps'] for d in base) / max(1, len(base)):.2f})")

    print("\nCharacters per second of speech (a drop would hint at lost words)")
    for bd in BANDS:
        b = [d["chars"] / d["audio"] for d in base if band(d["audio"]) == bd]
        t = [d["chars"] / d["audio"] for d in trial if band(d["audio"]) == bd]
        if b or t:
            fb = f"{median(b):5.1f} (n={len(b)})" if b else "    -"
            ft = f"{median(t):5.1f} (n={len(t)})" if t else "    -"
            print(f"  {label(bd):<10} baseline {fb:<14} trial {ft}")


if __name__ == "__main__":
    main()
