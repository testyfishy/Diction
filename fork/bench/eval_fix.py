"""Replay bench outputs through correction strategies and score them.
Usage: python3 eval_fix.py run.jsonl CLIPS_DIR VOCAB_TXT LIBRARY_TXT"""
import json, random, re, statistics, sys, time, unicodedata
from collections import defaultdict
import fuzzyfix as fz

NUM = {"67": "sixty seven", "14": "fourteen", "2": "two"}


def words(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9' ]", " ", s.lower().replace("-", " "))
    return " ".join(NUM.get(w, w) for w in s.split()).split()


def errors(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)], len(r)


def has_term(text, term):
    return " " + " ".join(words(term)) + " " in " " + " ".join(words(text)) + " "


def pseudo_terms(n, seed=3):
    """Drug-like made-up terms, to see what a 5,000-term table costs (speed and false fixes)."""
    rng = random.Random(seed)
    syl = ["ra", "ze", "mab", "tin", "lo", "pa", "zol", "vi", "ne", "pril", "sar", "ta", "ci", "do", "fen", "xa"]
    return ["".join(rng.choice(syl) for _ in range(rng.randint(3, 5))) for _ in range(n)]


def main():
    run, clips, vocab, library = sys.argv[1:5]
    eng = fz.load_english()
    hint = fz.load_terms(vocab)
    allt = fz.load_terms(vocab, library)
    lexes = {"none": None, "fuzzy 50 hint terms": fz.Lexicon(hint, eng),
             "fuzzy 268 terms": fz.Lexicon(allt, eng),
             "fuzzy 268 + 5000 made-up": fz.Lexicon(allt + pseudo_terms(5000), eng)}
    recs = [json.loads(l) for l in open(run) if l.startswith("{")]
    recs = [r for r in recs if not r.get("error")]
    by_label = defaultdict(list)
    for r in recs:
        by_label[r["label"]].append(r)
    print(f"{'output':<9}{'strategy':<26}{'wrong words/pass':>17}{'terms right':>13}{'fixes':>7}{'helped':>8}{'hurt':>6}{'ms/call':>9}")
    changes_seen = defaultdict(set)
    for label, rs in sorted(by_label.items()):
        passes = len(rs) / len({r["file"] for r in rs})
        for name, lex in lexes.items():
            tot_err = tot_terms = ok_terms = fixes = helped = hurt = 0
            times = []
            for r in rs:
                clip = r["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
                ref = open(f"{clips}/{clip}.txt").read()
                terms = [t.strip() for t in open(f"{clips}/{clip}.terms") if t.strip()]
                before, _ = errors(ref, r["final"])
                text = r["final"]
                if lex:
                    t0 = time.perf_counter()
                    text, ch = fz.correct(text, lex)
                    times.append((time.perf_counter() - t0) * 1000)
                    fixes += len(ch)
                    for c in ch:
                        changes_seen[name].add((c[0], c[1]))
                after, _ = errors(ref, text)
                helped += after < before
                hurt += after > before
                tot_err += after
                tot_terms += len(terms)
                ok_terms += sum(has_term(text, t) for t in terms)
            ms = f"{statistics.mean(times):.2f}" if times else "-"
            print(f"{label:<9}{name:<26}{tot_err / passes:>17.1f}{ok_terms / tot_terms * 100:>12.1f}%"
                  f"{fixes / passes:>7.1f}{helped / passes:>8.1f}{hurt / passes:>6.1f}{ms:>9}")
    for name, ch in changes_seen.items():
        print(f"\n{name}: distinct changes")
        for a, b in sorted(ch):
            print(f"   {a!r} -> {b!r}")


if __name__ == "__main__":
    main()
