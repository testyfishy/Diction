# Hermes fork of the Diction gateway

Branch `hermes/live-text` of `testyfishy/Diction`, based on upstream `release/v15.0`
(upstream `main` does not have the v15.0 `gateway/core` yet). It runs on a home server in
front of a self-hosted speech gateway that fronts Qwen3-ASR (served by GUFO). Upstream issue:
[DictionLabs/Diction#29](https://github.com/DictionLabs/Diction/issues/29).

## Read this first: live text needs the app makers

**We do not have the Diction iOS app's source.** Today's app reads exactly one frame after it
sends `{"action":"done"}` and inserts it as the final text, and it never asks a self-hosted
server for live text. So text appearing **while you speak** in the keyboard depends on the app
makers' update (issue #29; the developer has offered a TestFlight build). Until then:

- **Works today, no app change:** the segmented final. It cuts the wait after you stop talking
  from about 2 s to about 0.5 s.
- **Ready, waiting for the app:** live text (`?preview=cloud` → `interim` frames). It is
  deployed and tested with the test client in `hermes/streamclient`, but the current app never
  asks for it, so it does nothing yet.

A TestFlight invite needs only the email address of the Apple ID you use on the phone, not
an Apple developer account.

## What the fork changes

| Commit | What |
|---|---|
| Stream debug log | `DICTION_DEBUG_STREAM=true` logs, per dictation, the query string (unknown or long values redacted to their length), offered and negotiated subprotocols, how the audio frames arrived, and the time from `done` to text. It never logs audio, transcripts, the context frame or keys. |
| Segmented final + built-in preview | `gateway/core/live.go`. One engine per dictation cuts the audio at pauses and transcribes segments in the background, one request at a time, against the same backend with the same language, prompt and custom words as today's request. |
| This file + test tools | `hermes/streamclient` (speaks the app's protocol), `hermes/bench` (A/B bench and scorer). |

### How the segmented final works

1. Audio arrives as PCM, or as Opus that ffmpeg decodes as it arrives. (When either live
   feature is on, the Opus passthrough is turned off so the gateway has PCM while you talk;
   measured: ffmpeg keeps up with live Opus with no startup delay.)
2. A pause detector compares each 20 ms frame with a rolling noise floor (the quietest frame of
   the last 3 s, +10 dB, clamped to -60…-30 dBFS). A pause of `DICTION_SEGMENT_PAUSE_MS` after
   at least `DICTION_SEGMENT_MIN_MS` of audio ends a segment; past `DICTION_SEGMENT_MAX_MS` a
   `DICTION_SEGMENT_SHORT_PAUSE_MS` pause is enough.
3. A background worker sends each segment to the backend, one request in flight (a single-GPU
   ASR server serves one request at a time anyway). Backend-side hints, corrections and
   clean-up apply to each segment as they did to the whole clip.
4. On `done`: wait for a segment still in flight, transcribe only the tail since the last
   pause (skipped if it holds no speech), and join the texts. The join removes the full stop a
   cut puts in mid-sentence ("The plan is. After the MRI." → "The plan is after the MRI.")
   only when the word before it (the, and, of, is…) or after it (to, and, of…) cannot end or
   start a sentence.
5. **Fallback:** any segment or tail error, a degenerate (repeated-token) result, no speech
   detected at all, or a language change at `done` → today's single whole-clip request, with
   its retry logic. The engine is stopped first so nothing competes with it.

Known limits: the backend loses the audio *after* a cut as context. A word the model is
unsure of can then come out differently (see the accuracy note below). A backend correction
rule that spans a cut is missed. The 8 s minimum segment keeps both rare.

### How live text (the built-in preview) works

It answers `?preview=cloud` when no `core.PreviewRelay` hook is installed (the community
build) and `DICTION_PREVIEW=chunked`. Same engine: committed segments, plus the open segment
re-transcribed about once a second (`DICTION_PREVIEW_INTERVAL_MS`). Each
`{"type":"interim","text":"…"}` frame carries the whole transcript so far. Interims go through
upstream's existing `previewPump`, so none is ever written after the result.

Why not a realtime WebSocket or SSE backend: GUFO's realtime socket wants 24 kHz audio and
manual commits with no server VAD (so the same pause detector anyway), and it would bypass the
speech gateway's hints and corrections, so committed words would change when the final
arrives. SSE gives token deltas within one request, but each request here covers only the
open segment (a fraction of a second to decode) and the interim contract is "replace the whole
text", so deltas add nothing visible. Re-transcribing short segments over plain HTTP works with
any OpenAI-compatible backend, which also makes it a reasonable upstream PR.

Partials can go to a faster backend than the final (`DICTION_PREVIEW_URL`); here they go
straight to the ASR server without the hint prompt. Committed segments always use the
session's own backend, so they get hints and corrections; the final replaces any rough partial.

## Environment flags (all off by default)

| Variable | Default | Meaning |
|---|---|---|
| `DICTION_SEGMENTED_FINAL` | `false` | Transcribe at pauses while recording; only the tail after `done`. |
| `DICTION_PREVIEW` | `off` | `chunked` = answer `?preview=cloud` with interim frames (built-in relay). |
| `DICTION_SEGMENT_PAUSE_MS` | `700` | Pause that ends a segment. |
| `DICTION_SEGMENT_MIN_MS` | `8000` | Never cut a segment shorter than this. |
| `DICTION_SEGMENT_MAX_MS` | `20000` | Past this length, a short pause is enough. |
| `DICTION_SEGMENT_SHORT_PAUSE_MS` | `300` | The short pause. |
| `DICTION_PREVIEW_INTERVAL_MS` | `1000` | New audio needed before the open segment is re-transcribed. |
| `DICTION_PREVIEW_URL` / `_MODEL` / `_AUTH` | (session backend) | Optional separate backend for partials. |
| `DICTION_DEBUG_STREAM` | `false` | Per-dictation timing log (never text, audio or keys). |

## Measured results (2026-11-08)

Four synthetic 24–28 s dictations (TTS sentence by sentence, 0.8–1.5 s pauses, a -50 dBFS
noise floor, clinical and technical vocabulary); one has pauses in the middle of sentences.
Sent as Ogg/Opus paced in real time like the app (and as PCM for live text), against
throwaway containers, old and new never running at the same time. Word error rate ignores
punctuation and case.

| Clip | Upstream v15.0: wait after `done` | Fork, segmented: wait after `done` | Word errors, v15.0 → fork |
|---|---|---|---|
| technical | 1.90 s | **0.46 s** | 0 → 0 |
| mid-sentence pauses | 1.68 s | **0.51 s** | 0 → 0 (punctuation identical) |
| neurology clinic | 1.83 s | **0.46 s** | 0 → 1 |
| stroke note | 2.08 s | **0.78 s** | 1 → 1 |

Medians of 3 runs. Occasional runs take 0.2–0.5 s longer, when a segment is still being
transcribed at `done`.

The extra error: "lacosamide" came out as "lecanemab" (both are in the hint list). This word
is borderline for this voice even without segmenting: the first 18.8 s of the same clip, sent
whole, also gives "lecanemab"; only the full 24 s clip gives "lacosamide". Segmenting removes
the audio after the word, which here tipped it. With a 3 s minimum segment there were more
such errors and broken punctuation at mid-sentence pauses, which is why the default is 8 s.

Live text (PCM and Opus): first words appear 1.1–1.4 s after you start talking, then about
once a second (24–28 interims per clip). No interim ever arrived after the final text. The
wait after `done` stayed 0.45–0.8 s. Partials skip the hint prompt, so a drug name can look
wrong for a second until its segment is committed or the final arrives.

Tests: `go test ./...` passes. The new tests also pass under `-race`. Four existing streaming
tests fail under `-race` on untouched `release/v15.0` as well (races in the tests
themselves), so they are not caused by this branch.

## Speech gateway changes (on the server, not in this repo)

- **Prompt merge fix.** A caller `prompt` (Diction sends the user's My Words) used to
  *replace* the server's vocabulary hint. Now the caller's prompt comes first, untouched, and
  vocabulary terms fill the room left under the character cap, skipping terms the caller
  already named.
- **Fast path.** Input that is already 16 kHz mono 16-bit WAV (the Diction gateway's segments)
  skips the ffmpeg temp-file round trip.

## Deploy

```sh
# build (needs only podman; the Dockerfile is multi-stage). Run in gateway/.
podman build --build-arg VERSION=v15.0 --build-arg IMAGE_REF=localhost/diction-gateway:hermes-1 \
  -t localhost/diction-gateway:hermes-1 .
```

`VERSION=v15.0` matters: the app compares `/health`'s version with its own to decide whether
to warn that the gateway is outdated.

In the gateway's Quadlet (`~/.config/containers/systemd/diction-gateway.container`):
`Image=localhost/diction-gateway:hermes-1`, `Pull=never`, plus

```
Environment=DICTION_SEGMENTED_FINAL=true
Environment=DICTION_DEBUG_STREAM=true
Environment=DICTION_PREVIEW=chunked
Environment=DICTION_PREVIEW_URL=http://127.0.0.1:<asr port>
Environment=DICTION_PREVIEW_MODEL=<asr model id>
```

Then `systemctl --user daemon-reload && systemctl --user restart diction-gateway`. The data
volume (the pairing keyring) is untouched, so the phone stays paired.

## Rollback

The upstream v15.0 image is pinned locally as `localhost/diction-gateway:rollback-v15.0`, so a
later `latest` pull cannot move it, and the pre-fork Quadlet is kept as
`diction-gateway.container.bak-20261108-upstream`:

```sh
cd ~/.config/containers/systemd
cp diction-gateway.container.bak-20261108-upstream diction-gateway.container
systemctl --user daemon-reload && systemctl --user restart diction-gateway
```

Lighter option: set `DICTION_SEGMENTED_FINAL=false` and restart; the fork then sends the whole
clip exactly like v15.0.

## Testing without the phone

```sh
cd hermes/streamclient && go build .        # the test client
BACKEND_URL=http://127.0.0.1:<speech gateway port> BACKEND_MODEL=<model> \
  sh hermes/bench/bench.sh OLD_IMAGE NEW_IMAGE CLIPS_DIR out.jsonl 3
python3 hermes/bench/score.py out.jsonl CLIPS_DIR
```

`CLIPS_DIR` holds `<name>.ogg` (16 kHz Opus), `<name>.wav` (16 kHz PCM) and `<name>.txt` (the
script) per clip. The bench runs both images as throwaway containers on :8082/:8081 with auth
off, so no pairing key is involved.

## Proposed interim wire format (for the developer to agree)

Upstream's existing contract, unchanged:

1. The client opts in with `?preview=cloud` on `/v1/audio/stream`.
2. While recording, the server sends `{"type":"interim","text":"…"}` text frames. Each holds
   the **whole** transcript so far: replace, don't append.
3. No interim is sent after `done`'s result. The result frame (`{"text":…}`, no `type`) is the
   final text, exactly as today.

Proposed additions:

4. Interims are drafts. Words already shown may change, and a session may get no interims at
   all (preview off, or a slow backend). The app must never wait for one.
5. Preview works with Opus too: the built-in relay decodes Opus as it arrives, so the app does
   not have to switch to PCM to get live text. Sessions served by a `PreviewRelay` hook stay
   PCM-only, as upstream has it today.
6. Discovery: `/v1/models` could advertise `capabilities.preview: true` when the gateway will
   answer `preview=cloud`, so the app knows whether to ask. Not implemented until the name is
   agreed.
