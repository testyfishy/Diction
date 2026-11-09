"""Score streamclient JSON lines against the clip scripts.

    python3 score.py results.jsonl CLIPS_DIR

Per run label and clip: the MEAN over all passes of the time from "done" to the final text
(with min-max), the mean word error rate, and for live-text runs the mean time to the first
interim. Word error rate ignores case and punctuation; hyphens count as spaces, and the
digits the model writes for spoken numbers in our scripts count as those words.
"""
import json, re, statistics, sys
from collections import defaultdict

NUM = {"67": "sixty seven", "14": "fourteen", "2": "two"}


def words(s):
    s = re.sub(r"[^a-z0-9' ]", " ", s.lower().replace("-", " "))
    return " ".join(NUM.get(w, w) for w in s.split()).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r)), len(r)


def main():
    rows = defaultdict(list)
    for line in open(sys.argv[1]):
        if line.startswith("{"):
            rec = json.loads(line)
            clip = rec["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
            rows[(rec.get("label", "?"), clip)].append(rec)
    print(f"{'run':<14}{'clip':<11}{'passes':>7}{'mean wait after done':>22}{'min-max':>14}"
          f"{'mean WER':>10}{'errors/pass':>12}{'1st live word':>14}")
    for (label, clip), recs in sorted(rows.items()):
        ref = open(f"{sys.argv[2]}/{clip}.txt").read()
        ok = [r for r in recs if not r.get("error")]
        lat = [r["done_to_result_ms"] / 1000 for r in ok]
        scores = [wer(ref, r.get("final", "")) for r in ok]
        first = [r["interims"][0]["at_ms"] / 1000 for r in ok if r.get("interims")]
        mean = lambda xs: statistics.mean(xs) if xs else float("nan")
        print(f"{label:<14}{clip:<11}{len(ok):>4}/{len(recs):<2}{mean(lat):>20.2f} s"
              f"{(f'{min(lat):.2f}-{max(lat):.2f}' if lat else '-'):>14}"
              f"{mean([w for w, _ in scores]) * 100:>9.1f}%{mean([w * n for w, n in scores]):>12.1f}"
              f"{(f'{mean(first):.1f} s' if first else '-'):>14}")
        for r in recs:
            if r.get("error"):
                print("   error:", r["error"])
            if r.get("frames_after_final"):
                print("   FRAMES AFTER FINAL:", r["frames_after_final"])


if __name__ == "__main__":
    main()
