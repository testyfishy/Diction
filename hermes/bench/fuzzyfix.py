"""Fuzzy correction of a transcript against a term lexicon.

Rule: only words that are neither English (system dictionary) nor already a lexicon term
are candidates. A run of 1-3 such-containing words is compared with lexicon terms by
spelling and by a rough sound key; it is replaced only when the best term is close
(normalized edit distance <= MAX_SCORE) and clearly better than the runner-up.
"""
import re, time, unicodedata

MAX_SCORE = 0.25
MARGIN = 0.05
MIN_LEN = 5


def nwords(s):
    return len(re.split(r"[\s-]+", s.strip()))


def fold(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]", "", s)


def sound(s):
    """A rough English sound key: spellings that are pronounced alike map together."""
    s = fold(s)
    for a, b in (("ph", "f"), ("ck", "k"), ("qu", "kw"), ("x", "ks"), ("gh", "g"), ("th", "t"),
                 ("sch", "sk"), ("ch", "k"), ("wh", "w"), ("z", "s"), ("y", "i")):
        s = s.replace(a, b)
    s = re.sub(r"c(?=[eiy])", "s", s).replace("c", "k")
    s = re.sub(r"(.)\1+", r"\1", s)                       # double letters
    return s[:1] + re.sub(r"[aeiou]+", "a", s[1:])        # vowels mostly blur in ASR errors


def lev(a, b, cap):
    """Edit distance, giving up (returns cap+1) once it must exceed cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            best = min(best, cur[j])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def grams(s):
    s = "^" + s + "$"
    return {s[i:i + 3] for i in range(len(s) - 2)}


class Lexicon:
    def __init__(self, terms, english):
        self.english = english
        self.terms = []
        seen = set()
        for t in terms:
            f = fold(t)
            if len(f) >= MIN_LEN and f not in seen:
                seen.add(f)
                self.terms.append((t, f, sound(t), nwords(t)))
        self.exact = {f for _, f, _, _ in self.terms}
        # Index: each term under its 3-letter chunks (spelling and sound), so a lookup only
        # compares terms that share chunks with the word, however big the table gets.
        self.index = {}
        for i, (_, tf, ts, _) in enumerate(self.terms):
            for g in grams(tf) | grams(ts):
                self.index.setdefault(g, set()).add(i)

    def candidates(self, f, s):
        gs = grams(f) | grams(s)
        hits = {}
        for g in gs:
            for i in self.index.get(g, ()):
                hits[i] = hits.get(i, 0) + 1
        # A real near-miss shares a good part of its chunks; at most 25% of letters differ.
        need = max(2, len(gs) // 3)
        return [self.terms[i] for i, n in hits.items() if n >= need]

    def best(self, span, nwords):
        f, s = fold(span), sound(span)
        cap = int(len(f) * MAX_SCORE)
        scored = []
        for t, tf, ts, tn in self.candidates(f, s):
            if tn != nwords or abs(len(tf) - len(f)) > cap:
                continue
            d = min(lev(f, tf, cap), lev(s, ts, cap))
            if d <= cap:
                scored.append((d / max(len(f), len(tf)), t))
        scored.sort()
        if not scored:
            return None
        if len(scored) > 1 and scored[1][0] - scored[0][0] < MARGIN and scored[1][1] != scored[0][1]:
            return None                                    # ambiguous: leave it
        return scored[0]


TOKEN = re.compile(r"[\w'’-]+|[^\w\s]+|\s+", re.UNICODE)


def correct(text, lex):
    toks = TOKEN.findall(text)
    words = [i for i, t in enumerate(toks) if re.match(r"[\w'’-]", t)]

    def is_known(w):
        lw = fold(w)
        return w.lower() in lex.english or lw in lex.english or lw in lex.exact or len(lw) < MIN_LEN

    out, changes, k = list(toks), [], 0
    while k < len(words):
        done = False
        for n in (3, 2, 1):
            if k + n > len(words):
                continue
            idx = words[k:k + n]
            # a span must be contiguous words (only spaces/hyphens between) and contain a non-word
            if any(not re.fullmatch(r"\s+", "".join(toks[idx[j] + 1:idx[j + 1]]) or " ") for j in range(n - 1)):
                continue
            span_words = [toks[i] for i in idx]
            if all(is_known(w) for w in span_words):
                continue
            span = " ".join(span_words)
            hit = lex.best(span, nwords(span))
            if hit and fold(hit[1]) != fold(span):
                rep = hit[1]
                if span_words[0][:1].isupper() and rep[:1].islower():
                    rep = rep[:1].upper() + rep[1:]   # keep a sentence-start capital
                out[idx[0]] = rep
                for i in range(idx[0] + 1, idx[-1] + 1):
                    out[i] = ""
                changes.append((span, hit[1], round(hit[0], 3)))
                k += n
                done = True
                break
        if not done:
            k += 1
    return "".join(out), changes


def load_english(path="/usr/share/dict/words"):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return {w.strip().lower() for w in f if w.strip()}


def load_terms(*paths):
    terms = []
    for p in paths:
        for line in open(p, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            terms.append(line.split("=>", 1)[1].strip() if "=>" in line else line)
    return terms


if __name__ == "__main__":
    eng = load_english()
    lex = Lexicon(["lacosamide", "NIHSS", "rimegepant", "andexanet alfa", "Guillain-Barré syndrome"], eng)
    for s in ["We started lecasmide today.", "The NIHISS was high.", "Rimagepant helped.",
              "Give andexanet alpha now.", "This is Guillain Bare syndrome.", "She is fine and walking."]:
        t = time.perf_counter()
        print(correct(s, lex), f"{(time.perf_counter() - t) * 1000:.2f} ms")
