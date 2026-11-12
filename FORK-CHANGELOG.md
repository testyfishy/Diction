# Fork changelog

Changes in this fork relative to upstream `release/v15.0`, newest first. Features are
described in [FORK.md](FORK.md); bug fixes are tracked here. Fixes to unchanged upstream
code are also kept on the `upstream-fixes` branch, based on upstream `main`, so they can be
taken without the fork's features.

## v15.0-fork.3

### Fixes

- **Invented text typed after a near-silent recording.** A backend can answer a very short or
  near-silent clip with text it was never given in audio (for example its own prompt). In
  pieces mode each piece was already held to a bound of 25 characters per second of audio
  plus 20, but the whole-recording fallback was not, so the invented answer was returned
  after a second, equally slow request.
  - *Fix:* when the only piece is the whole recording and it breaks the bound, the gateway
    returns an empty result without asking again; the whole-recording fallback is held to
    the same bound. Applies only with `DICTION_SEGMENTED_FINAL=true`; with it off the
    backend's answer is passed on as upstream does.
  - *Tests:* `gateway/core/live_invented_test.go`.

### Added

- Live-text verification: `fork/bench/live_text.sh`, `live_text_report.py` and
  `noisy_decoder.sh`, with results in [FORK.md](FORK.md#live-text-and-pieces-together-verification).

### Changed

- Documented `DICTION_PREVIEW_INTERVAL_MS` and the known limits of live text.

## v15.0-fork.2

### Fixes

- **Sessions failed the decode check after 4 KB of ffmpeg warnings.** `limitedStderrWriter`
  (the capped buffer that collects ffmpeg's stderr) returned the truncated length once its cap
  was reached. `os/exec` treats that as a short write: it stops draining stderr and returns
  the short write from `Wait` as the command's error, even when ffmpeg decoded everything and
  exited cleanly. A process that keeps writing can also be killed by SIGPIPE.
  - *Effect in the fork:* on Opus sessions whose decoder emitted more than 4 KB of warnings
    the decode check failed (`live: decode incomplete`) and the gateway fell back to the whole
    recording, so those sessions got upstream speed instead of pieces. No text was lost.
  - *Scope:* the writer is unchanged upstream code, so any ffmpeg decode that emits more than
    4 KB of warnings is affected there too.
  - *Fix:* report the full length; the cap still bounds what is kept. With the debug log on,
    the decoder's exit state, stderr size and first stderr line are logged.
  - *Tests:* `gateway/core/stderr_writer_test.go`.
  - *On its own:* branch [`upstream-fixes`](https://github.com/testyfishy/Diction/tree/upstream-fixes)
    carries this fix alone on top of upstream `main`, without any fork feature.

### Added

- `/v1/models` advertises live text: `capabilities.preview`, and `preview_opus` when ffmpeg is
  present. Both follow `DICTION_PREVIEW=chunked` and are false by default.
- Debug log line per session with live text: draft count, first-draft time and backend time
  (numbers only).

### Changed

- Fork files renamed: notes in `FORK.md`, tools in `fork/`, charts in `assets/fork/`, branch
  `live-text`.

## v15.0-fork.1

- Pieces mode (`DICTION_SEGMENTED_FINAL`), with a longer first piece
  (`DICTION_SEGMENT_FIRST_MIN_MS`).
- Built-in live text (`DICTION_PREVIEW=chunked`) for PCM and Opus sessions.
- Per-session debug log (`DICTION_DEBUG_STREAM`).
- Test tools: stream client, benchmark and analysis scripts.
