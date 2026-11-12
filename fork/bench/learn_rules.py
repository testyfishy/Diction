"""Learn "heard => written" rules from training dictations, the way a user would build a
table from their own mistakes: wherever a known term came out wrong, record what the model
wrote instead. Rules are only learned for lexicon terms, and only when what was heard looks
like a mishearing (it contains a non-English word, or is several words).

    python3 learn_rules.py TRAIN_RUN.jsonl TRAIN_CLIPS VOCAB.txt LIBRARY.txt > rules.txt
"""
import json, sys
from collections import Counter
import fuzzyfix as fz
from eval_fix import words


FUNCTION = {"a", "an", "the", "and", "but", "or", "of", "to", "it", "is", "in", "on", "at", "for", "with", "so"}


def align(ref, hyp):
    """Word alignment (edit distance with backtrace) -> list of (ref_span, hyp_span) diffs."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, ops = n, m, []
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("=" if ref[i - 1] == hyp[j - 1] else "~", ref[i - 1], hyp[j - 1])); i -= 1; j -= 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append(("-", ref[i - 1], None)); i -= 1
        else:
            ops.append(("+", None, hyp[j - 1])); j -= 1
    ops.reverse()
    diffs, r, h = [], [], []
    for op, a, b in ops + [("=", None, None)]:
        if op == "=":
            if r or h:
                diffs.append((r, h))
            r, h = [], []
        else:
            if a: r.append(a)
            if b: h.append(b)
    return diffs


def main():
    run, clips, vocab, library = sys.argv[1:5]
    eng = fz.load_english()
    terms = fz.load_terms(vocab, library)
    term_words = {" ".join(words(t)): t for t in terms}
    rules = Counter()
    for line in open(run):
        if not line.startswith("{"):
            continue
        r = json.loads(line)
        clip = r["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        ref = words(open(f"{clips}/{clip}.txt").read())
        for rs, hs in align(ref, words(r["final"])):
            if not hs:
                continue
            # widen to the whole term when the diff covers part of a multi-word term
            rspan = " ".join(rs)
            target = next((t for k, t in term_words.items() if rspan and rspan in k.split() or rspan == k), None)
            if target is None:
                target = next((t for k, t in term_words.items() if k in rspan), None)
            if target is None:
                continue
            if len(hs) > 4:
                continue                       # a garbled run, not a reusable rule
            spelled = all(len(x) == 1 for x in hs) and target.isupper()   # "c s f" => CSF
            if not spelled:
                # trim small function words at the edges ("but peladema", "a pixaban")
                tw = set(words(target))
                while len(hs) > 1 and hs[0] in FUNCTION and hs[0] not in tw:
                    hs = hs[1:]
                while len(hs) > 1 and hs[-1] in FUNCTION and hs[-1] not in tw:
                    hs = hs[:-1]
                if all(x in eng for x in hs):
                    continue                   # ordinary English ("it figures", "of a tumor"): too risky
            heard = " ".join(hs)
            if " ".join(words(target)) == heard:
                continue
            rules[(heard, target)] += 1
    for (heard, target), n in sorted(rules.items(), key=lambda x: -x[1]):
        print(f"{heard} => {target}    # seen {n}x")


if __name__ == "__main__":
    main()
