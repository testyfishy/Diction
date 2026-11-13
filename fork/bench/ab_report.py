"""Report on an ab_upstream.sh run. Prints numbers only, never transcript text.

    python3 ab_report.py OUT.jsonl [CLIPS_DIR]

Per length band: the wait from "done" to the final text for the upstream image and for the
fork (median and worst), the fork's first draft and drafts per second, and, when CLIPS_DIR
has NAME.txt reference scripts, the word error rate of each final. Then, per clip, how often
the fork's final was faster, and whether it had fewer, the same or more wrong words.
"""
import json, os, re, sys
from statistics import mean, median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import wer, words  # noqa: E402

BANDS = (("under 5 s", 0, 5), ("5-15 s", 5, 15), ("15-30 s", 15, 30), ("30-60 s", 30, 60), ("over 60 s", 60, 1e9))


def band(ms):
    return next(name for name, lo, hi in BANDS if lo <= ms / 1000 < hi)


def main():
    path = sys.argv[1]
    clips = sys.argv[2] if len(sys.argv) > 2 else None
    rows, per_clip, errors = {}, {}, 0
    for line in open(path):
        if not line.startswith("{"):
            continue
        r = json.loads(line)
        if r.get("error"):
            errors += 1
            continue
        clip = os.path.splitext(os.path.basename(r["file"]))[0]
        ims = r.get("interims") or []
        ref = None
        if clips and os.path.exists(os.path.join(clips, clip + ".txt")):
            ref = open(os.path.join(clips, clip + ".txt")).read()
        rate, nref = wer(ref, r["final"]) if ref else (0, 0)
        x = {"wait": r["done_to_result_ms"] / 1000, "wrong": rate * nref, "nref": nref,
             "first": ims[0]["at_ms"] / 1000 if ims else None,
             "rate": len(ims) / (r["audio_ms"] / 1000), "empty": not words(r["final"]),
             "text": " ".join(words(r["final"]))}
        rows.setdefault((band(r["audio_ms"]), r["label"]), []).append(x)
        per_clip.setdefault(clip, {}).setdefault(r["label"], []).append(x)

    print(f"{'length':<11}{'image':<10}{'runs':>5}{'final wait':>12}{'(worst)':>9}{'first draft':>13}{'drafts/s':>10}{'wrong words':>13}")
    for name, _, _ in BANDS:
        for label in ("upstream", "fork"):
            xs = rows.get((name, label))
            if not xs:
                continue
            firsts = [x["first"] for x in xs if x["first"] is not None]
            nref = sum(x["nref"] for x in xs)
            c_first = f"{median(firsts):.2f}s" if firsts else "-"
            c_rate = f"{median(x['rate'] for x in xs):.1f}" if firsts else "-"
            c_wrong = f"{sum(x['wrong'] for x in xs) / nref * 100:.1f}%" if nref else "-"
            c_wait = f"{median(x['wait'] for x in xs):.2f}s"
            c_max = f"{max(x['wait'] for x in xs):.2f}s"
            print(f"{name:<11}{label:<10}{len(xs):>5}{c_wait:>12}{c_max:>9}{c_first:>13}{c_rate:>10}{c_wrong:>13}")

    faster = slower = fewer = same = more = scored = ident = both = 0
    for clip, by in per_clip.items():
        if "upstream" not in by or "fork" not in by:
            continue
        both += 1
        ident += bool({x["text"] for x in by["upstream"]} & {x["text"] for x in by["fork"]})
        u, f = mean(x["wait"] for x in by["upstream"]), mean(x["wait"] for x in by["fork"])
        faster += f < u
        slower += f > u
        if by["fork"][0]["nref"]:
            scored += 1
            wu, wf = mean(x["wrong"] for x in by["upstream"]), mean(x["wrong"] for x in by["fork"])
            fewer += wf < wu - 0.01
            more += wf > wu + 0.01
            same += abs(wf - wu) <= 0.01
    print()
    print(f"clips where the fork's final was faster: {faster} of {faster + slower}")
    print(f"clips with reference text ({scored}): fork has fewer wrong words on {fewer}, the same on {same}, more on {more}")
    print(f"clips where both images gave the same final text: {ident} of {both}")
    print(f"empty finals: {sum(x['empty'] for xs in rows.values() for x in xs)}; client errors: {errors}")
    log = path + ".log"
    if os.path.exists(log):
        text = open(log).read()
        print(f"fork log: fallbacks to the whole recording {len(re.findall(r'live: final ok=false', text))}, "
              f"decode checks failed {len(re.findall(r'decode incomplete', text))}, "
              f"pieces failed {len(re.findall(r'segment failed', text))}")


if __name__ == "__main__":
    main()
