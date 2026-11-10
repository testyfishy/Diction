# Plan: live text with the Diction app, then true streaming

Status 2026-11-09. Upstream thread: [DictionLabs/Diction#29](https://github.com/DictionLabs/Diction/issues/29).
How pieces, live text and true streaming differ: see `HERMES-FORK.md`.

## What the app maker asked for

1. **The app has to ask for live text.** Today it reads one frame, after `done`. He will add
   live text for self-hosted servers and send a TestFlight build to test against Qwen3-ASR
   (the owner emails him the TestFlight address).
2. **Gateway side, build on `core.PreviewRelay`** (`gateway/core/preview.go`): it gets PCM,
   returns `{"type":"interim","text":"…"}` frames, each the whole transcript so far. A PR
   wiring it to an SSE or realtime backend is welcome.
3. **Agree the wire format before either side ships.**

## Constraints found here

- **The app sends Opus** (211 of 211 logged sessions). The hook is PCM-only: an Opus session
  gets no relay. Our live engine already decodes Opus as it arrives (ffmpeg, kept up in real
  time in tests), so the gateway feeds the relay PCM either way: PCM sessions directly, Opus
  sessions decoded on arrival. No app requirement, so no need to ask; raise it in the PR.
- **The hook's signature is `(ctx, language)`**: no backend, prompt or custom words. A relay
  that re-transcribes with the session's own backend and hint list needs those.
- **GUFO's Qwen3-ASR does not stream input** (tests in `HERMES-FORK.md`). Drafts on this model
  are re-transcriptions of the open piece, about one per second.

## Steps

**1. Tell him where we are (now).** A short comment on #29: yes to TestFlight, the pieces
trial on Strix Halo in one paragraph, a link to the fork. No questions; detail stays in the
fork. Owner's approval before posting. (Which branch a PR targets: ask when a PR is ready.)

**2. Move the built-in preview behind the hook (gateway, before TestFlight).** Make the
built-in preview a `PreviewSession` implementation, so the app talks to one interface
whatever produces the drafts:
- *Pieces relay* (default): re-transcribes the open piece with the session's backend, shares
  cuts with pieces mode. Exists today as `DICTION_PREVIEW=chunked`; only the plumbing changes.
- *Realtime relay* (`DICTION_PREVIEW=realtime`, `DICTION_PREVIEW_URL=ws://…`): an
  OpenAI-realtime client for backends that do stream (step 4). With GUFO it degrades to
  commit-per-pause, so the pieces relay stays the default here.
- Propose widening the hook (backend + prompt in a context or options struct) and feeding it
  from Opus sessions. Unit tests for both relays; off by default; final text unchanged.

**3. Test the TestFlight build against the live server.** Same metrics log as the trial,
plus: time to first draft, drafts per second, how often shown words change (flicker), and
whether the final ever arrives later than without drafts (drafts and pieces share one GPU).
Target: first draft under 1.5 s, final unchanged (0.4–0.8 s), no lost dictations.

**4. True streaming for the drafts (experiment).** Try a streaming-native speech model on
Strix Halo for drafts only, behind the realtime relay, with Qwen3-ASR kept for the final.
Candidates to check for ROCm/Vulkan support first: cache-aware streaming Parakeet/Nemotron
models, Kyutai's streaming STT, and whether a newer GUFO adds incremental decoding for
Qwen3-ASR. Measure draft latency and how close drafts are to the final; GPU memory next to
Halogen is the hard limit.

**5. Upstream PR** once the wire format is agreed: the hook-based relays and the segmented
final, without the fork-only `HERMES-FORK.md` and `hermes/`.

## Wire format to propose (his C2, unchanged, plus three additions)

1. Opt in with `?preview=cloud` on `/v1/audio/stream`.
2. While recording: `{"type":"interim","text":"…"}`, each the whole transcript so far
   (replace, don't append).
3. Nothing after the result; the result frame is as today.
4. Drafts are drafts: shown words can change, a session may get none, never wait for one.
5. Works on Opus sessions (the gateway decodes as audio arrives).
6. Discovery: `capabilities.preview: true` on `/v1/models` when the gateway answers it.
