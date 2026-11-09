"""Offline test of "fast draft from pieces, then repair the uncertain words with more context".

For each test clip, using the cut points the gateway actually chose (from its debug log), it
asks the speech gateway for: the whole recording, each piece, and, for pieces with uncertain
words, a wider window (piece before + piece + piece after). All in one session, so model
drift hits every variant alike. Levels scored:

  whole              the whole recording (today's upstream)
  pieces             pieces joined
  pieces+table       each piece through the lookup table (fuzzy + optional learned rules)
  pieces+table+fix   uncertain words (neither English nor a known term, after the table)
                     replaced by what the wider window heard at that spot

Wait after "done" = the last piece, plus any repair window that needs audio from after the
last cut (repairs of earlier pieces run while the user is still talking).

    SPEECH_URL=http://127.0.0.1:PORT python3 sim_repair.py CLIPS_DIR DECODED_WAV_DIR GATEWAY_LOG VOCAB LIBRARY [RULES] [PASSES]
"""
import io, json, re, statistics, sys, time, urllib.request, uuid, wave
from collections import defaultdict
import fuzzyfix as fz
from eval_fix import errors, has_term, words

import os
SGW = os.environ.get("SPEECH_URL", "") + "/v1/audio/transcriptions"   # e.g. http://127.0.0.1:PORT


def asr(pcm, rate, a, b):
    o = io.BytesIO()
    with wave.open(o, "wb") as x:
        x.setnchannels(1); x.setsampwidth(2); x.setframerate(rate)
        x.writeframes(pcm[int(a * rate) * 2:int(b * rate) * 2])
    bd = uuid.uuid4().hex
    body = b"".join(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in (("model", "qwen3-asr-clean"), ("language", "en")))
    body += (f'--{bd}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
             f"Content-Type: audio/wav\r\n\r\n").encode() + o.getvalue() + f"\r\n--{bd}--\r\n".encode()
    req = urllib.request.Request(SGW, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + bd})
    t = time.monotonic()
    text = json.load(urllib.request.urlopen(req, timeout=300))["text"]
    return text, time.monotonic() - t


def cuts_from_log(path, clips):
    """Session n in the new gateway's log is clip n (bench order); collect its cut points."""
    cuts, n = defaultdict(list), 0
    for line in open(path):
        if "ws debug: open" in line:
            n += 1
        m = re.search(r"live: segment \d+ \(([\d.]+)s-([\d.]+)s\)", line)
        if m and n <= len(clips):
            cuts[clips[n - 1]].append(float(m.group(2)))
    return cuts


def main():
    clipdir, wavdir, log, vocab, library = sys.argv[1:6]
    rules_path = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] != "-" else None
    passes = int(sys.argv[7]) if len(sys.argv) > 7 else 1
    import os
    clips = sorted(f[:-4] for f in os.listdir(clipdir) if f.endswith(".ogg"))
    cuts = cuts_from_log(log, clips)
    eng = fz.load_english()
    hint_terms, all_terms = fz.load_terms(vocab), fz.load_terms(vocab, library)
    lex_small, lex_large = fz.Lexicon(hint_terms, eng), fz.Lexicon(all_terms, eng)
    rules = fz.load_rules(rules_path) if rules_path else []
    known_words = {w for t in all_terms for w in words(t)}
    tables = {
        "no table": lambda t: t,
        "table: 50 hint terms": lambda t: fz.correct(t, lex_small)[0],
        "table: 268 terms": lambda t: fz.correct(t, lex_large)[0],
        "table: 268 terms + learned rules": lambda t: fz.correct(fz.apply_rules(t, rules), lex_large)[0],
    }

    def uncertain(w):
        """Low confidence: neither English nor part of a known term."""
        return len(w) >= 3 and not w.isdigit() and w not in eng and w not in known_words

    rows = []          # (name, err, words, terms_frac, wait, windows)
    for p in range(passes):
        for c in clips:
            ref = open(f"{clipdir}/{c}.txt").read()
            terms = [t.strip() for t in open(f"{clipdir}/{c}.terms") if t.strip()]
            w = wave.open(f"{wavdir}/{c}.wav"); rate = w.getframerate(); pcm = w.readframes(w.getnframes())
            end = len(pcm) / 2 / rate
            bounds = [0.0] + cuts[c] + [end]
            n = len(bounds) - 1
            whole, t_whole = asr(pcm, rate, 0, end)
            pieces = [asr(pcm, rate, bounds[i], bounds[i + 1]) for i in range(n)]
            t_last = pieces[-1][1]
            windows = {}   # (lo, hi) -> (text, seconds); shared by every table level

            def score(name, text, wait, nwin=0):
                e, nw = errors(ref, text)
                rows.append((name, e, nw, sum(has_term(text, t) for t in terms) / len(terms), wait, nwin))

            score("whole recording (upstream)", whole, t_whole)
            score("whole recording + best table", tables["table: 268 terms + learned rules"](whole), t_whole)
            line = [f"pass {p + 1} {c}: whole {errors(ref, whole)[0]}"]
            for tname, tf in tables.items():
                tabled = [tf(t) for t, _ in pieces]
                draft = " ".join(tabled)
                score(f"pieces, {tname}", draft, t_last)
                # confidence repair
                fixed = [words(t) for t in tabled]
                after_done, nwin = 0.0, 0
                for k in range(n):
                    if not any(uncertain(x) for x in fixed[k]):
                        continue
                    lo, hi = max(0, k - 1), min(n, k + 2)
                    if (lo, hi) not in windows:
                        windows[(lo, hi)] = asr(pcm, rate, bounds[lo], bounds[hi])
                    wtext, wdt = windows[(lo, hi)]
                    nwin += 1
                    if hi == n:
                        after_done += wdt        # needs the last piece's audio: after "done"
                    span = sum(fixed[lo:hi], [])
                    starts = [sum(len(x) for x in fixed[lo:j]) for j in range(lo, hi + 1)]
                    new = splice(span, words(tf(wtext)), set(range(starts[k - lo], starts[k - lo + 1])), uncertain)
                    tail_len = len(span) - starts[k - lo + 1]
                    fixed[k] = new[starts[k - lo]:len(new) - tail_len]
                repaired = " ".join(" ".join(x) for x in fixed)
                score(f"pieces, {tname} + confidence fix", repaired, t_last + after_done, nwin)
                line.append(f"{tname.split(':')[-1].strip()[:12]} {errors(ref, draft)[0]}/{errors(ref, repaired)[0]}")
            print(" | ".join(line), flush=True)

    order = []
    for r in rows:
        if r[0] not in order:
            order.append(r[0])
    print(f"\n{'level':<52}{'wrong words':>12}{'terms right':>13}{'wait':>8}{'windows':>9}")
    for name in order:
        rs = [r for r in rows if r[0] == name]
        print(f"{name:<52}{sum(r[1] for r in rs) / sum(r[2] for r in rs) * 100:>11.1f}%"
              f"{statistics.mean(r[3] for r in rs) * 100:>12.1f}%{statistics.mean(r[4] for r in rs):>7.2f}s"
              f"{statistics.mean(r[5] for r in rs):>9.2f}")


def splice(draft, window, region, uncertain):
    """Take the window's words for each diff region that overlaps `region` and holds an
    uncertain draft word; keep the draft everywhere else."""
    out, i = [], 0
    for rs, hs, start in diffs_with_pos(draft, window):
        out.extend(draft[i:start])
        i = start
        span = range(start, start + len(rs))
        if any(j in region for j in span) and any(uncertain(draft[j]) for j in span):
            out.extend(hs)
        else:
            out.extend(rs)
        i = start + len(rs)
    out.extend(draft[i:])
    return out


def diffs_with_pos(ref, hyp):
    """Like align(), with the start index of each diff in ref."""
    pos, res, ri = 0, [], 0
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
            ops.append(("=" if ref[i - 1] == hyp[j - 1] else "~", i - 1, j - 1)); i -= 1; j -= 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            ops.append(("-", i - 1, None)); i -= 1
        else:
            ops.append(("+", None, j - 1)); j -= 1
    ops.reverse()
    cur_r, cur_h, start, ri = [], [], None, 0
    for op, a, b in ops:
        if op == "=":
            if cur_r or cur_h:
                res.append((cur_r, cur_h, start if start is not None else ri))
            cur_r, cur_h, start = [], [], None
            ri = a + 1
            continue
        if start is None:
            start = a if a is not None else ri
        if a is not None:
            cur_r.append(ref[a]); ri = a + 1
        if b is not None:
            cur_h.append(hyp[b])
    if cur_r or cur_h:
        res.append((cur_r, cur_h, start if start is not None else ri))
    return res


if __name__ == "__main__":
    main()
