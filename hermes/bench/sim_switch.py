"""Where should dictation switch from "whole recording" to "pieces"? Offline sweep.

Hybrid mode T: the first piece is at least T seconds long (so a dictation shorter than T is
sent whole), then normal pieces (8 s minimum, cut at 0.7 s pauses). T = 8 is plain pieces;
T = inf is the whole recording.

Each test clip is also cut short at its natural pauses, giving dictations of many lengths
from the same speech. The reference for a shortened clip is the script up to the matching
word (found by aligning the plain-pieces transcript, whose piece ends are known times).
Every mode's text goes through the lookup table (268 terms), as in production. Cuts come
from a Python port of the gateway's pause detector (gateway/core/live.go), checked against
the cuts the gateway logged.

    SPEECH_URL=http://127.0.0.1:PORT python3 sim_switch.py VOCAB LIBRARY OUT.jsonl \
        CLIPS_DIR:WAV_DIR:GATEWAY_LOG [CLIPS_DIR:WAV_DIR:GATEWAY_LOG ...]

Writes one JSON row per (clip, length, mode): errors, reference words, model seconds after
"done" (the last piece, or the whole recording).
"""
import json, math, os, struct, sys, wave
import fuzzyfix as fz
from eval_fix import errors, words
from sim_repair import asr, cuts_from_log

FRAME = 320                      # 20 ms at 16 kHz
PAUSE_MS, MIN_MS, MAX_MS, SHORT_PAUSE_MS = 700, 8000, 20000, 300
FLOOR_N, ABOVE_DB, TH_MIN, TH_MAX, MIN_VOICED_MS = 150, 10.0, -60.0, -30.0, 300
MODES = [8, 15, 20, 25, 30, 40, 60]   # T in seconds; plus "whole"


def frame_db(pcm):
    n = len(pcm) // 2 // FRAME
    out = []
    for i in range(n):
        s = struct.unpack_from("<%dh" % FRAME, pcm, i * FRAME * 2)
        rms = math.sqrt(sum(x * x for x in s) / FRAME)
        out.append(-96.0 if rms < 1 else 20 * math.log10(rms / 32768))
    return out


def detect(dbs, nframes, first_min_ms):
    """The gateway's pauseDetector.push, with the first segment's minimum raised to
    first_min_ms (and its maximum to at least that). Returns cut times in seconds."""
    floor, cuts = [], []
    seg_start, voiced, silence, sil_start = 0, 0, 0, 0
    for i in range(nframes):
        db = dbs[i]
        floor.append(db)
        lo = min(floor[-FLOOR_N:])
        speech = max(TH_MIN, min(TH_MAX, lo + ABOVE_DB))
        if db > speech:
            voiced += 1; silence = 0
            continue
        if silence == 0:
            sil_start = i
        silence += 1
        seg_ms = (i + 1 - seg_start) * 20
        first = not cuts
        mn = max(MIN_MS, first_min_ms) if first else MIN_MS
        mx = max(MAX_MS, first_min_ms + MAX_MS - MIN_MS) if first else MAX_MS
        need = SHORT_PAUSE_MS if seg_ms >= mx else PAUSE_MS
        if voiced * 20 >= MIN_VOICED_MS and seg_ms >= mn and silence * 20 >= need:
            at = sil_start + silence / 2          # in frames
            cuts.append(at * FRAME / 16000)
            seg_start = int(at); voiced = 0
    return cuts


def align_ends(ref_words, hyp_pieces):
    """Reference word index reached at the end of each hypothesis piece (edit-distance
    alignment of the joined pieces against the reference)."""
    hyp = [w for p in hyp_pieces for w in p]
    n, m = len(ref_words), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): d[i][0] = i
    for j in range(m + 1): d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (ref_words[i - 1] != hyp[j - 1]))
    ref_at = [0] * (m + 1)                       # ref index aligned after hyp word j
    i, j = n, m
    while j > 0:
        if i > 0 and d[i][j] == d[i - 1][j - 1] + (ref_words[i - 1] != hyp[j - 1]):
            ref_at[j] = i; i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            ref_at[j] = i; j -= 1
    ends, k = [], 0
    for p in hyp_pieces:
        k += len(p); ends.append(ref_at[k])
    return ends


def main():
    vocab, library, out_path = sys.argv[1:4]
    lex = fz.Lexicon(fz.load_terms(vocab, library), fz.load_english())
    table = lambda t: fz.correct(t, lex)[0]
    out = open(out_path, "w")
    cache = {}

    def tr(pcm, a, b):
        key = (round(a, 2), round(b, 2))
        if key not in cache:
            cache[key] = asr(pcm, 16000, a, b)
        return cache[key]

    for spec in sys.argv[4:]:
        clipdir, wavdir, log = spec.split(":")
        clips = sorted(f[:-4] for f in os.listdir(clipdir) if f.endswith(".ogg"))
        logged = cuts_from_log(log, clips)
        for c in clips:
            cache.clear()
            w = wave.open(f"{wavdir}/{c}.wav"); assert w.getframerate() == 16000
            pcm = w.readframes(w.getnframes()); end = len(pcm) / 2 / 16000
            dbs = frame_db(pcm); nf = len(dbs)
            base = detect(dbs, nf, 0)
            drift = max((min(abs(x - y) for y in base) for x in logged[c]), default=0)
            print(f"{c}: {end:.0f}s, cuts {len(base)} (gateway logged {len(logged[c])}, "
                  f"max diff {drift:.2f}s)", flush=True)
            ref = words(open(f"{clipdir}/{c}.txt").read())
            bounds = [0.0] + base + [end]
            pieces = [words(table(tr(pcm, bounds[i], bounds[i + 1])[0])) for i in range(len(bounds) - 1)]
            ref_end = align_ends(ref, pieces)
            # shortened versions end at each plain-pieces cut, plus the full clip
            for k, L in enumerate(bounds[1:]):
                ref_l = " ".join(ref[:ref_end[k]])
                if len(ref_l.split()) < 5:
                    continue
                nfl = min(nf, int(L * 16000) // FRAME)
                rows = {}
                text, t = tr(pcm, 0, L)
                rows["whole"] = (table(text), t, 1)
                for T in MODES:
                    cs = [x for x in detect(dbs, nfl, T * 1000) if x < L - 0.05]
                    b = [0.0] + cs + [L]
                    parts = [tr(pcm, b[i], b[i + 1]) for i in range(len(b) - 1)]
                    rows[f"T{T}"] = (" ".join(table(p[0]) for p in parts), parts[-1][1], len(parts))
                for mode, (text, t, npieces) in rows.items():
                    e, nw = errors(ref_l, text)
                    out.write(json.dumps({"clip": c, "len": round(L, 2), "mode": mode, "err": e,
                                          "ref_words": nw, "wait": round(t, 3), "pieces": npieces}) + "\n")
                out.flush()


if __name__ == "__main__":
    main()
