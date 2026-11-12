"""Report on a live_text.sh run. Prints numbers only, never transcript text.

    python3 live_text_report.py OUT.jsonl [CLIPS_DIR]

Per length band it compares a client that does not ask for live text ("off") with one that
does ("drafts"): the wait from "done" to the final text, when the first draft arrived, how
many drafts per second, how much of the final the last draft already held, and (when
CLIPS_DIR has NAME.txt reference scripts) the word error rate of the final. It then checks
the things that must hold: drafts on every run that asked, the same final text either way,
nothing sent after the final, and no fallbacks in the gateway log (OUT.jsonl.log).
"""
import json, os, re, sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import wer, words  # noqa: E402

BANDS = (("under 5 s", 0, 5), ("5-15 s", 5, 15), ("15-30 s", 15, 30), ("30-60 s", 30, 60), ("over 60 s", 60, 1e9))


def band(ms):
    return next(name for name, lo, hi in BANDS if lo <= ms / 1000 < hi)


def held(final, draft):
    """Share of the final's words the last draft already had, in order."""
    f, d = words(final), words(draft)
    if not f:
        return 1.0
    i = 0
    for w in d:
        for j in range(i, min(i + 4, len(f))):
            if f[j] == w:
                i = j + 1
                break
    return i / len(f)


def main():
    path = sys.argv[1]
    clips = sys.argv[2] if len(sys.argv) > 2 else None
    rows, errors = {}, 0
    finals = {}
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
        rate, nref = wer(ref, r["final"]) if ref else (None, 0)
        finals.setdefault((clip, r["label"]), []).append(" ".join(words(r["final"])))
        rows.setdefault((band(r["audio_ms"]), r["label"]), []).append({
            "wait": r["done_to_result_ms"] / 1000, "n": len(ims),
            "first": ims[0]["at_ms"] / 1000 if ims else None,
            "rate": len(ims) / (r["audio_ms"] / 1000),
            "held": held(r["final"], ims[-1]["text"]) if ims else None,
            "wrong": rate * nref if ref else None, "nref": nref,
            "after": r.get("frames_after_final", 0), "empty": not words(r["final"])})

    print(f"{'length':<11}{'client':<8}{'runs':>5}{'final wait':>12}{'(max)':>8}{'first draft':>13}"
          f"{'drafts/s':>10}{'last draft holds':>18}{'wrong words':>13}")
    for name, _, _ in BANDS:
        for label in ("off", "drafts"):
            xs = rows.get((name, label))
            if not xs:
                continue
            firsts = [x["first"] for x in xs if x["first"] is not None]
            helds = [x["held"] for x in xs if x["held"] is not None]
            nref = sum(x["nref"] for x in xs)
            wrong = sum(x["wrong"] or 0 for x in xs)
            c_first = f"{median(firsts):.2f}s" if firsts else "-"
            c_rate = f"{median(x['rate'] for x in xs):.1f}" if firsts else "-"
            c_held = f"{median(helds) * 100:.0f}% of final" if helds else "-"
            c_wrong = f"{wrong / nref * 100:.1f}%" if nref else "-"
            c_wait = f"{median(x['wait'] for x in xs):.2f}s"
            c_max = f"{max(x['wait'] for x in xs):.2f}s"
            print(f"{name:<11}{label:<8}{len(xs):>5}{c_wait:>12}{c_max:>8}{c_first:>13}{c_rate:>10}{c_held:>18}{c_wrong:>13}")

    asked = [x for (b, label), xs in rows.items() if label == "drafts" for x in xs]
    same = total = 0
    for (clip, label), fs in finals.items():
        if label != "drafts":
            continue
        ref = set(finals.get((clip, "off"), []))
        for f in fs:
            total += 1
            same += f in ref
    unstable = sum(len(set(fs)) > 1 for (clip, label), fs in finals.items() if label == "off")
    print()
    print(f"runs that asked for drafts and got none: {sum(1 for x in asked if x['n'] == 0)} of {len(asked)}")
    print(f"finals with drafts identical to a drafts-off final of the same clip: {same} of {total}"
          f" (clips whose drafts-off finals differ between passes: {unstable})")
    print(f"frames after the final: {sum(x['after'] for xs in rows.values() for x in xs)}")
    print(f"empty finals: {sum(x['empty'] for xs in rows.values() for x in xs)}; client errors: {errors}")
    log = path + ".log"
    if os.path.exists(log):
        text = open(log).read()
        ok = len(re.findall(r"live: final ok=true", text))
        pieces = len(re.findall(r"live: final ok=true segments=[1-9]", text))
        print(f"gateway log: finals from the live engine {ok} (with pieces done during dictation: {pieces}), "
              f"fallbacks to the whole recording {len(re.findall(r'live: final ok=false', text))}, "
              f"decode checks failed {len(re.findall(r'decode incomplete', text))}, "
              f"pieces failed {len(re.findall(r'segment failed', text))}, "
              f"invented answers dropped {len(re.findall(r'more text than', text))}")


if __name__ == "__main__":
    main()
