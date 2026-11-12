"""Per clip: whole recording vs pieces, mean wrong words and wait over passes.
Usage: python3 pairs.py run.jsonl CLIPS_DIR [A_LABEL B_LABEL]"""
import json, statistics, sys
from collections import defaultdict
from eval_fix import errors

run, clips = sys.argv[1], sys.argv[2]
A, B = (sys.argv[3], sys.argv[4]) if len(sys.argv) > 4 else ("old", "pieces8")
err, lat = defaultdict(list), defaultdict(list)
for l in open(run):
    if not l.startswith("{"):
        continue
    r = json.loads(l)
    if r.get("error"):
        continue
    clip = r["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
    err[(r["label"], clip)].append(errors(open(f"{clips}/{clip}.txt").read(), r["final"])[0])
    lat[(r["label"], clip)].append(r["done_to_result_ms"] / 1000)
names = sorted({c for _, c in err})
better = worse = same = 0
print(f"{'clip':<16}{'words':>6}{A + ' errors':>14}{B + ' errors':>16}{A + ' wait':>12}{B + ' wait':>14}")
for c in names:
    n = len(open(f"{clips}/{c}.txt").read().split())
    ea, eb = statistics.mean(err[(A, c)]), statistics.mean(err[(B, c)])
    better += eb < ea
    worse += eb > ea
    same += eb == ea
    print(f"{c:<16}{n:>6}{ea:>14.1f}{eb:>16.1f}{statistics.mean(lat[(A, c)]):>11.2f}s{statistics.mean(lat[(B, c)]):>13.2f}s")
ta = sum(statistics.mean(err[(A, c)]) for c in names)
tb = sum(statistics.mean(err[(B, c)]) for c in names)
words = sum(len(open(f"{clips}/{c}.txt").read().split()) for c in names)
print(f"\nall {len(names)} clips, {words} words: {A} {ta:.1f} wrong ({ta / words * 100:.1f}%), "
      f"{B} {tb:.1f} wrong ({tb / words * 100:.1f}%). {B} better on {better}, worse on {worse}, same on {same}.")
print(f"mean wait: {A} {statistics.mean(sum((lat[(A, c)] for c in names), [])):.2f}s, "
      f"{B} {statistics.mean(sum((lat[(B, c)] for c in names), [])):.2f}s")
passes = {k: len(v) for k, v in err.items()}
print("passes per clip:", sorted(set(passes.values())))
