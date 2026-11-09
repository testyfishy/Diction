"""Make the benchmark dictations: text-to-speech sentence by sentence, joined with pauses we
choose, plus a quiet noise floor, then encoded the way the Diction app sends audio.

    python3 make_clips.py OUT_DIR TTS_URL

TTS_URL is an OpenAI-compatible /v1/audio/speech endpoint that returns raw 24 kHz 16-bit
mono PCM for response_format=pcm (we used Qwen3-TTS-12Hz-1.7B-CustomVoice, voice "aiden").
Needs python3 and ffmpeg with libopus on PATH. Writes per clip:
  <name>.ogg  16 kHz mono Ogg/Opus, 16 kb/s, VoIP mode, 200 ms pages (what the bench sends)
  <name>.wav  16 kHz mono 16-bit PCM (for PCM / live-text runs)
  <name>.txt  the script, the reference for word error rate

TTS output varies run to run, so the exact audio we measured is committed next to this
file (clips/*.ogg); regenerate only to make a new test set.
"""
import json, os, random, struct, subprocess, sys, urllib.request, wave, zlib

RATE = 24000          # TTS output rate
LEAD_S = 0.4          # silence before the first word
TAIL_S = 0.5          # silence after the last word, before "done"
NOISE_DBFS = -50.0    # Gaussian noise floor over everything (a quiet room), seeded per clip
VOICE = "aiden"

# Each clip: (sentence or fragment, pause after it in seconds). The pauses are what the
# server cuts at; "midpause" pauses in the middle of sentences, the hard case.
CLIPS = {
    "technical": [
        ("I restarted the podman Quadlet on the Strix Halo box this morning.", 1.0),
        ("The GUFO speech gateway now reloads the vocabulary file on every request.", 1.3),
        ("Tailscale serve exposes it only inside the tailnet.", 0.9),
        ("Next I want to check whether the dictation socket stays stable overnight.", 1.4),
        ("If it does not, roll back to the previous image and open an issue.", 0),
    ],
    "midpause": [
        ("The plan for this patient is,", 0.9),
        ("after the repeat MRI,", 1.0),
        ("to start levetiracetam at a low dose and", 1.1),
        ("titrate up over two weeks.", 1.2),
        ("If the EEG shows", 0.8),
        ("ongoing discharges we will add lacosamide.", 1.0),
        ("I also want a lipid panel because her LDL is still high on evolocumab.", 0),
    ],
    "clinic": [
        ("She has a long history of migraine without aura.", 1.0),
        ("Rimegepant helped with acute attacks but ubrogepant did not.", 1.2),
        ("Her MRI was normal apart from a few small white matter lesions.", 1.0),
        ("We discussed starting lacosamide if the spells turn out to be seizures.", 1.5),
        ("Please send a referral to the epilepsy clinic and copy Dr. Nguyen.", 0),
    ],
    "stroke": [
        ("Patient is a sixty seven year old man with atrial fibrillation on apixaban.", 1.2),
        ("He presented with sudden left sided weakness this morning.", 1.0),
        ("The NIHSS on arrival was fourteen.", 1.5),
        ("CT angiography showed a basilar artery occlusion.", 1.0),
        ("We gave tenecteplase and he went straight for thrombectomy.", 1.2),
        ("Please arrange follow up with Dr. Patel in clinic next week.", 0),
    ],
}


def tts(url, text, voice=VOICE):
    body = json.dumps({"input": text, "voice": voice, "response_format": "pcm"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main():
    """make_clips.py OUT_DIR TTS_URL [standard|training]: the 4-clip set, the 16-clip standard set
    (standard_set.py, two voices; also writes <name>.terms, the target terms to score)."""
    if len(sys.argv) < 3:
        sys.exit("usage: make_clips.py OUT_DIR TTS_URL [standard|training]")
    out, url = sys.argv[1], sys.argv[2]
    clips = {name: (VOICE, [], parts) for name, parts in CLIPS.items()}
    if len(sys.argv) > 3 and sys.argv[3] in ("standard", "training"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        if sys.argv[3] == "standard":
            from standard_set import STANDARD as clips
        else:
            from training_set import TRAINING as clips
    os.makedirs(out, exist_ok=True)
    for name, (voice, terms, parts) in clips.items():
        rng = random.Random(zlib.crc32(name.encode()))
        samples = [0.0] * int(LEAD_S * RATE)
        for text, pause in parts:
            samples += [s for (s,) in struct.iter_unpack("<h", tts(url, text, voice))]
            samples += [0.0] * int(pause * RATE)
        samples += [0.0] * int(TAIL_S * RATE)
        amp = 32768 * 10 ** (NOISE_DBFS / 20)
        pcm = [max(-32768, min(32767, round(s + rng.gauss(0, amp)))) for s in samples]
        raw = os.path.join(out, name + ".24k.wav")
        with wave.open(raw, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
            w.writeframes(struct.pack("<%dh" % len(pcm), *pcm))
        base = os.path.join(out, name)
        ffmpeg("-i", raw, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", base + ".wav")
        ffmpeg("-i", raw, "-ar", "16000", "-ac", "1", "-c:a", "libopus", "-b:a", "16k",
               "-application", "voip", "-page_duration", "200000", base + ".ogg")
        os.remove(raw)
        with open(base + ".txt", "w") as f:
            f.write(" ".join(t for t, _ in parts) + "\n")
        if terms:
            with open(base + ".terms", "w") as f:
                f.write("\n".join(terms) + "\n")
        print(f"{name}: {len(pcm) / RATE:.1f} s")


if __name__ == "__main__":
    main()
