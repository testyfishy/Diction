"""Score streamclient JSON lines against the clip scripts: latency after done, word error rate.
Usage: python3 score.py results.jsonl clips_dir"""
import json, re, statistics, sys
from collections import defaultdict

NUM = {"67": "sixty seven", "14": "fourteen", "2": "two"}


def norm(s):
    s = s.lower().replace("-", " ")
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    return [NUM.get(w, w) for w in " ".join(NUM.get(w, w) for w in s.split()).split()]


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


def main():
    rows = defaultdict(list)
    for line in open(sys.argv[1]):
        line = line.strip()
        if not line.startswith("{"):
            continue
        rec = json.loads(line)
        clip = rec["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        ref = open(f"{sys.argv[2]}/{clip}.txt").read()
        rows[(rec.get("label", "?"), clip, rec["codec"])].append(rec | {"wer": wer(ref, rec.get("final", "")) if not rec.get("error") else None})
    print(f"{'run':<14}{'clip':<10}{'codec':<6}{'n':>3}{'done->result ms (median, each)':>36}{'WER':>7}{'interims':>9}{'1st interim s':>14}")
    for (label, clip, codec), recs in sorted(rows.items()):
        ok = [r for r in recs if not r.get("error")]
        lat = [r["done_to_result_ms"] for r in ok]
        w = [r["wer"] for r in ok]
        its = [len(r.get("interims") or []) for r in ok]
        first = [r["interims"][0]["at_ms"] / 1000 for r in ok if r.get("interims")]
        each = ",".join(str(x) for x in lat)
        print(f"{label:<14}{clip:<10}{codec:<6}{len(recs):>3}{(str(int(statistics.median(lat))) + ' (' + each + ')') if lat else 'ERR':>36}"
              f"{(statistics.mean(w) * 100 if w else float('nan')):>6.1f}%{(statistics.mean(its) if its else 0):>9.1f}"
              f"{(min(first) if first else float('nan')):>14.1f}")
        for r in recs:
            if r.get("error"):
                print("   error:", r["error"])
            if r.get("frames_after_final"):
                print("   FRAMES AFTER FINAL:", r["frames_after_final"])


if __name__ == "__main__":
    main()
