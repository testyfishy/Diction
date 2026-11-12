# Fork changelog

Changes in this fork relative to upstream `release/v15.0`, newest first. Features are
described in [FORK.md](FORK.md); bug fixes are tracked here.

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
