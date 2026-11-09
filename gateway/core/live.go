package core

import (
	"bytes"
	"context"
	"encoding/binary"
	"log"
	"math"
	"net/url"
	"strings"
	"sync"
	"time"
)

// Live transcription on the batch socket, for self-hosted backends.
//
// One engine per /v1/audio/stream session watches the PCM as it arrives (16 kHz s16le
// mono: raw PCM frames, or Opus decoded by the existing ffmpeg pipe) and cuts it into
// segments at pauses. A single background worker sends one request at a time to the
// session's own backend, so it never competes with itself for the GPU. It serves two
// features, both off by default:
//
//   - Segmented final (DICTION_SEGMENTED_FINAL): segments are transcribed while the user
//     is still talking, so after `done` only the tail since the last pause is left.
//     Any failure falls back to today's single whole-clip request.
//   - Built-in preview (DICTION_PREVIEW=chunked): the open segment is re-transcribed
//     about once a second and `{"type":"interim"}` frames carry the whole transcript so
//     far (committed segments + the open one). It answers `?preview=cloud` when no
//     PreviewRelay hook is installed, and works with any OpenAI-compatible backend.

// LiveConfig holds the env-tunable settings. The zero value disables everything.
type LiveConfig struct {
	Segmented bool // DICTION_SEGMENTED_FINAL
	Preview   bool // DICTION_PREVIEW=chunked

	PauseMs     int // a pause this long ends a segment (DICTION_SEGMENT_PAUSE_MS)
	MinSegMs    int // segments shorter than this are never cut (DICTION_SEGMENT_MIN_MS)
	MaxSegMs    int // past this length a short pause is enough (DICTION_SEGMENT_MAX_MS)
	ShortPauseMs int // the pause needed past MaxSegMs

	PartialEveryMs int // preview: re-transcribe the open segment after this much new audio

	// Optional separate backend for preview partials (e.g. the ASR server directly,
	// skipping slower post-processing). Empty URL = the session's own backend.
	PreviewURL   string
	PreviewModel string
	PreviewAuth  string

	Debug bool // DICTION_DEBUG_STREAM: log timings and cut decisions (never text)
}

// LiveConfigFromEnv reads the DICTION_SEGMENT*, DICTION_PREVIEW* and DICTION_DEBUG_STREAM variables.
func LiveConfigFromEnv() LiveConfig {
	return LiveConfig{
		Segmented:      EnvBoolOrDefault("DICTION_SEGMENTED_FINAL", false),
		Preview:        strings.EqualFold(EnvOrDefault("DICTION_PREVIEW", "off"), "chunked"),
		PauseMs:        EnvIntOrDefault("DICTION_SEGMENT_PAUSE_MS", 700),
		MinSegMs:       EnvIntOrDefault("DICTION_SEGMENT_MIN_MS", 8000),
		MaxSegMs:       EnvIntOrDefault("DICTION_SEGMENT_MAX_MS", 20000),
		ShortPauseMs:   EnvIntOrDefault("DICTION_SEGMENT_SHORT_PAUSE_MS", 300),
		PartialEveryMs: EnvIntOrDefault("DICTION_PREVIEW_INTERVAL_MS", 1000),
		PreviewURL:     EnvOrDefault("DICTION_PREVIEW_URL", ""),
		PreviewModel:   EnvOrDefault("DICTION_PREVIEW_MODEL", ""),
		PreviewAuth:    EnvOrDefault("DICTION_PREVIEW_AUTH", ""),
		Debug:          EnvBoolOrDefault("DICTION_DEBUG_STREAM", false),
	}
}

const (
	liveSampleRate   = 16000
	liveFrameSamples = 320 // 20 ms
	liveFrameMs      = 20
	liveFrameBytes   = liveFrameSamples * 2
	// The noise floor is the quietest frame of the last 3 s; speech is >10 dB above it.
	liveFloorWindow   = 150
	liveSpeechAboveDB = 10.0
	liveThresholdMin  = -60.0 // below this is silence whatever the floor
	liveThresholdMax  = -30.0 // above this is speech whatever the floor
	liveMinVoicedMs   = 300   // a segment needs this much speech to be cut
	liveTailVoicedMs  = 120   // the tail is skipped below this much speech
)

// pauseDetector finds cut points in 16 kHz s16le PCM. Positions are in samples.
type pauseDetector struct {
	cfg LiveConfig

	rem       []byte
	pos       int64 // samples processed
	floor     [liveFloorWindow]float64
	floorN    int
	segStart  int64
	voiced    int // speech frames since segStart
	silence   int // consecutive silent frames
	silStart  int64
}

type liveCut struct {
	at     int64 // sample position
	voiced int   // speech frames in the segment it closes
}

func frameDBFS(frame []byte) float64 {
	var sum float64
	n := len(frame) / 2
	for i := 0; i < n; i++ {
		s := float64(int16(binary.LittleEndian.Uint16(frame[2*i:])))
		sum += s * s
	}
	rms := math.Sqrt(sum / float64(n))
	if rms < 1 {
		return -96
	}
	return 20 * math.Log10(rms/32768)
}

func (d *pauseDetector) threshold() float64 {
	n := d.floorN
	if n > liveFloorWindow {
		n = liveFloorWindow
	}
	lo := 0.0
	for i := 0; i < n; i++ {
		if i == 0 || d.floor[i] < lo {
			lo = d.floor[i]
		}
	}
	th := lo + liveSpeechAboveDB
	return math.Max(liveThresholdMin, math.Min(liveThresholdMax, th))
}

// push consumes PCM and returns any cuts it completes.
func (d *pauseDetector) push(p []byte) []liveCut {
	var cuts []liveCut
	if len(d.rem) > 0 {
		p = append(d.rem, p...)
		d.rem = nil
	}
	for len(p) >= liveFrameBytes {
		frame := p[:liveFrameBytes]
		p = p[liveFrameBytes:]
		db := frameDBFS(frame)
		d.floor[d.floorN%liveFloorWindow] = db
		d.floorN++
		frameStart := d.pos
		d.pos += liveFrameSamples
		if db > d.threshold() {
			d.voiced++
			d.silence = 0
			continue
		}
		if d.silence == 0 {
			d.silStart = frameStart
		}
		d.silence++
		segMs := int((d.pos - d.segStart) * 1000 / liveSampleRate)
		need := d.cfg.PauseMs
		if d.cfg.MaxSegMs > 0 && segMs >= d.cfg.MaxSegMs {
			need = d.cfg.ShortPauseMs
		}
		if d.voiced*liveFrameMs >= liveMinVoicedMs && segMs >= d.cfg.MinSegMs && d.silence*liveFrameMs >= need {
			// Cut in the middle of the pause seen so far: both sides keep some silence.
			at := d.silStart + int64(d.silence*liveFrameSamples/2)
			cuts = append(cuts, liveCut{at: at, voiced: d.voiced})
			d.segStart = at
			d.voiced = 0
		}
	}
	if len(p) > 0 {
		d.rem = append([]byte(nil), p...)
	}
	return cuts
}

// liveTranscribeFunc transcribes one WAV (16 kHz mono s16). It must honour ctx.
type liveTranscribeFunc func(ctx context.Context, wav []byte) (string, error)

// liveEngine runs one session's segmentation and its single background worker.
type liveEngine struct {
	cfg        LiveConfig
	final      liveTranscribeFunc // segments and tail (the session's backend, full prompt)
	partial    liveTranscribeFunc // preview partials; nil = no preview
	ctx        context.Context
	cancel     context.CancelFunc
	wake       chan struct{}
	workerDone chan struct{}
	closeOnce  sync.Once

	mu        sync.Mutex
	det       pauseDetector
	pcm       []byte // audio from base on (committed audio is dropped)
	base      int64  // sample position of pcm[0]
	pending   []liveCut
	texts     []string // committed segment texts, in order
	committed int64    // sample position up to which texts cover the audio
	failed    error
	finishing bool
	busy      bool // a segment job is running

	partialCancel  context.CancelFunc
	partialFrom    int64 // committed position the last partial was computed from
	partialAt      int64 // audio length when the last partial was started
	interims       chan string
	interimsClosed bool

	segments   int
	segmentMs  int64 // total backend time spent on segments while recording
}

func newLiveEngine(parent context.Context, cfg LiveConfig, final, partial liveTranscribeFunc) *liveEngine {
	ctx, cancel := context.WithCancel(parent)
	e := &liveEngine{
		cfg: cfg, final: final, partial: partial,
		ctx: ctx, cancel: cancel,
		wake: make(chan struct{}, 1), workerDone: make(chan struct{}),
		interims: make(chan string, 1),
		det:      pauseDetector{cfg: cfg},
	}
	if partial == nil {
		e.interimsClosed = true
		close(e.interims)
	}
	go e.worker()
	return e
}

// Write feeds PCM. Safe to call from any one goroutine at a time; never blocks on the backend.
func (e *liveEngine) Write(p []byte) (int, error) {
	e.mu.Lock()
	if !e.finishing {
		e.pcm = append(e.pcm, p...)
		for _, c := range e.det.push(p) {
			if e.cfg.Debug {
				log.Printf("live: cut at %.2fs (segment %d speech frames)", float64(c.at)/liveSampleRate, c.voiced)
			}
			e.pending = append(e.pending, c)
		}
	}
	e.mu.Unlock()
	e.poke()
	return len(p), nil
}

func (e *liveEngine) poke() {
	select {
	case e.wake <- struct{}{}:
	default:
	}
}

// audioEnd is the sample position of the end of the received audio. Caller holds mu.
func (e *liveEngine) audioEnd() int64 { return e.base + int64(len(e.pcm)/2) }

// slice returns a WAV of [from, to). Caller holds mu.
func (e *liveEngine) wav(from, to int64) []byte {
	a := (from - e.base) * 2
	b := (to - e.base) * 2
	var buf bytes.Buffer
	buf.Grow(int(b-a) + 44)
	WriteWAVHeader(&buf, int(b-a)) //nolint:errcheck — bytes.Buffer cannot fail
	buf.Write(e.pcm[a:b])
	return buf.Bytes()
}

// commit records a segment's text and drops its audio. Caller holds mu.
func (e *liveEngine) commit(to int64, text string) {
	if t := strings.TrimSpace(text); t != "" {
		e.texts = append(e.texts, t)
	}
	drop := (to - e.base) * 2
	e.pcm = append([]byte(nil), e.pcm[drop:]...)
	e.base = to
	e.committed = to
}

func (e *liveEngine) committedText() string { return joinSegments(e.texts) }

// Words that (almost) never end a sentence, and words that (almost) never start one.
// A backend punctuates every segment as if it were complete, so a cut at a mid-sentence
// pause comes back as "The plan is. After the MRI. To start…". These lists decide when
// that full stop is an artefact of the cut. They are deliberately short: a word that can
// end a sentence ("not", "her", "that", "will") or start one ("When", "After", "Then")
// is left out, because joining two real sentences is worse than a stray full stop.
var (
	segDanglingEnd = setOf("a", "an", "the", "and", "or", "nor", "of", "to", "for", "with", "from",
		"into", "is", "are", "was", "were", "been", "am", "if", "because", "than", "my", "our",
		"your", "their", "shows", "showed", "including", "per", "plus", "versus", "vs")
	segContinuingStart = setOf("and", "or", "nor", "to", "of", "than", "whom", "whose", "plus",
		"versus", "including")
)

func setOf(words ...string) map[string]bool {
	m := make(map[string]bool, len(words))
	for _, w := range words {
		m[w] = true
	}
	return m
}

func firstWord(s string) string {
	f := strings.Fields(s)
	if len(f) == 0 {
		return ""
	}
	return strings.Trim(f[0], ",;:.!?")
}

func lastWord(s string) string {
	f := strings.Fields(s)
	if len(f) == 0 {
		return ""
	}
	return strings.TrimRight(f[len(f)-1], ".,;:")
}

// keepCapital reports whether a segment's first word must keep its capital: "I", acronyms
// (two or more capitals, like MRI or EEG) and words with digits.
func keepCapital(w string) bool {
	if w == "I" || strings.HasPrefix(w, "I'") {
		return true
	}
	upper := 0
	for _, r := range w {
		if r >= '0' && r <= '9' {
			return true
		}
		if r >= 'A' && r <= 'Z' {
			upper++
		}
	}
	return upper >= 2
}

// joinSegments joins segment texts, removing the full stop a cut put in mid-sentence:
// when a segment ends in a word that rarely ends a sentence, or the next starts with a
// word that rarely starts one, the stop goes and the next word is lowercased (unless it
// is "I", an acronym or has digits). Question and exclamation marks are kept.
func joinSegments(texts []string) string {
	var b strings.Builder
	for _, t := range texts {
		t = strings.TrimSpace(t)
		if t == "" {
			continue
		}
		if b.Len() == 0 {
			b.WriteString(t)
			continue
		}
		prev := b.String()
		next := firstWord(t)
		if strings.HasSuffix(prev, ".") && !strings.HasSuffix(prev, "..") &&
			(segDanglingEnd[strings.ToLower(lastWord(prev))] || segContinuingStart[strings.ToLower(next)]) {
			b.Reset()
			b.WriteString(strings.TrimSuffix(prev, "."))
			if next != "" && !keepCapital(next) {
				t = strings.ToLower(t[:1]) + t[1:]
			}
		}
		b.WriteString(" ")
		b.WriteString(t)
	}
	return b.String()
}

// emit publishes an interim, replacing any the writer has not taken yet. Caller holds mu.
func (e *liveEngine) emit(text string) {
	if e.interimsClosed || text == "" {
		return
	}
	select {
	case e.interims <- text:
	default:
		select {
		case <-e.interims:
		default:
		}
		e.interims <- text
	}
}

func (e *liveEngine) worker() {
	defer close(e.workerDone)
	for {
		select {
		case <-e.wake:
		case <-e.ctx.Done():
			return
		}
		for e.step() {
		}
		e.mu.Lock()
		stop := e.finishing || e.failed != nil
		e.mu.Unlock()
		if stop {
			return
		}
	}
}

// step runs at most one job. Segments come first; a partial runs only when no
// segment is waiting. Returns whether it did anything.
func (e *liveEngine) step() bool {
	e.mu.Lock()
	if e.finishing || e.failed != nil || e.ctx.Err() != nil {
		e.mu.Unlock()
		return false
	}
	if len(e.pending) > 0 {
		// Everything cut so far goes in one request (normally just one segment).
		last := e.pending[len(e.pending)-1]
		e.pending = nil
		from := e.committed
		wav := e.wav(from, last.at)
		e.busy = true
		e.mu.Unlock()

		start := time.Now()
		text, err := e.final(e.ctx, wav)
		if err == nil && hasDegenerateRepetition(text) {
			err = errSTTHallucination
		}
		ms := time.Since(start).Milliseconds()

		e.mu.Lock()
		e.busy = false
		if err != nil {
			e.failed = err
			e.mu.Unlock()
			if e.cfg.Debug {
				// The hint, never the error: a backend error body can hold the user's words.
				_, hint, _ := classifyBackendFailure(err)
				log.Printf("live: segment failed after %dms: %s", ms, hint)
			}
			return false
		}
		e.commit(last.at, text)
		e.segments++
		e.segmentMs += ms
		if e.cfg.Debug {
			log.Printf("live: segment %d (%.2fs-%.2fs) took %dms", e.segments,
				float64(from)/liveSampleRate, float64(last.at)/liveSampleRate, ms)
		}
		e.emit(e.committedText())
		e.mu.Unlock()
		return true
	}
	if e.partial == nil || e.interimsClosed {
		e.mu.Unlock()
		return false
	}
	end := e.audioEnd()
	open := end - e.committed
	grown := end - e.partialAt
	if e.partialFrom != e.committed {
		grown = open
	}
	if grown*1000/liveSampleRate < int64(e.cfg.PartialEveryMs) || e.det.voiced*liveFrameMs < liveMinVoicedMs {
		e.mu.Unlock()
		return false
	}
	from := e.committed
	wav := e.wav(from, end)
	pctx, pcancel := context.WithCancel(e.ctx)
	e.partialCancel = pcancel
	e.partialFrom, e.partialAt = from, end
	e.mu.Unlock()

	text, err := e.partial(pctx, wav)
	pcancel()

	e.mu.Lock()
	e.partialCancel = nil
	// A segment may have committed meanwhile; this partial is then stale.
	if err == nil && e.committed == from && !hasDegenerateRepetition(text) {
		joined := joinSegments(append(append([]string(nil), e.texts...), text))
		e.emit(joined)
	}
	e.mu.Unlock()
	return true
}

// stopInterims closes the interim channel; the engine keeps running for the final.
func (e *liveEngine) stopInterims() {
	e.mu.Lock()
	if !e.interimsClosed {
		e.interimsClosed = true
		close(e.interims)
	}
	if e.partialCancel != nil {
		e.partialCancel()
	}
	e.mu.Unlock()
}

// liveFinish describes how the segmented final went, for logs.
type liveFinish struct {
	segments  int
	segmentMs int64
	tailSec   float64
	tailMs    int64
	waitMs    int64 // time spent waiting for an in-flight segment after done
}

// Finish ends recording: it waits for an in-flight segment, transcribes the tail and
// returns the joined text. ok=false means the caller must use the whole-clip request.
func (e *liveEngine) Finish(ctx context.Context) (string, bool, liveFinish) {
	var st liveFinish
	e.mu.Lock()
	e.finishing = true
	if e.partialCancel != nil {
		e.partialCancel()
	}
	e.mu.Unlock()
	e.poke()
	waitStart := time.Now()
	select {
	case <-e.workerDone:
	case <-ctx.Done():
		return "", false, st
	}
	st.waitMs = time.Since(waitStart).Milliseconds()

	e.mu.Lock()
	st.segments, st.segmentMs = e.segments, e.segmentMs
	if e.failed != nil {
		e.mu.Unlock()
		return "", false, st
	}
	// Pending cuts that never started are simply part of the tail.
	tailVoiced := e.det.voiced
	for _, c := range e.pending {
		tailVoiced += c.voiced
	}
	end := e.audioEnd()
	st.tailSec = float64(end-e.committed) / liveSampleRate
	var wav []byte
	if tailVoiced*liveFrameMs >= liveTailVoicedMs && end > e.committed {
		wav = e.wav(e.committed, end)
	}
	texts := append([]string(nil), e.texts...)
	e.mu.Unlock()

	if wav != nil {
		start := time.Now()
		text, err := e.final(ctx, wav)
		st.tailMs = time.Since(start).Milliseconds()
		if err != nil || hasDegenerateRepetition(text) {
			return "", false, st
		}
		if t := strings.TrimSpace(text); t != "" {
			texts = append(texts, t)
		}
	}
	if len(texts) == 0 {
		// Nothing heard, or the detector misjudged the audio: let the whole clip decide.
		return "", false, st
	}
	return joinSegments(texts), true, st
}

// Close stops the worker and any request in flight. Idempotent.
func (e *liveEngine) Close() {
	e.closeOnce.Do(func() {
		e.cancel()
		<-e.workerDone
		e.stopInterims()
	})
}

// livePreview adapts the engine to PreviewSession. The handler feeds the engine
// directly (it also sees decoded Opus), so Send is a no-op. Stop ends the interims
// only; the handler owns the engine's lifetime (the segmented final may still need it).
type livePreview struct{ e *liveEngine }

func (p livePreview) Send([]byte)              {}
func (p livePreview) Interims() <-chan string { return p.e.interims }
func (p livePreview) Stop()                   { p.e.stopInterims() }

// startLive opens a session's engine against the backend routing chose, with the same
// language, prompt and custom words the whole-clip request would send — so segment
// text goes through exactly the same backend-side processing as today's final.
func (g *Gateway) startLive(ctx context.Context, target *url.URL, backend *Backend, upstreamLanguage, contextJSON string, preview bool) *liveEngine {
	prompt := buildWhisperPrompt(contextJSON)
	customWords := buildCustomWordsField(contextJSON)
	final := func(ctx context.Context, wav []byte) (string, error) {
		return g.proxyToBackend(ctx, target, audioPayload{data: wav, filename: "audio.wav"}, backend, upstreamLanguage, prompt, customWords)
	}
	var partial liveTranscribeFunc
	if preview {
		partial = final
		if g.live.PreviewURL != "" {
			if pu, err := url.Parse(g.live.PreviewURL); err == nil && pu.Host != "" {
				pb := &Backend{Name: "preview", ForwardModel: g.live.PreviewModel, AuthHeader: g.live.PreviewAuth}
				partial = func(ctx context.Context, wav []byte) (string, error) {
					return g.proxyToBackend(ctx, pu, audioPayload{data: wav, filename: "audio.wav"}, pb, upstreamLanguage, "", "")
				}
			} else {
				log.Printf("live: DICTION_PREVIEW_URL is not a URL; partials use the session backend")
			}
		}
	}
	return newLiveEngine(ctx, g.live, final, partial)
}

// close is the nil-safe Close for the handler's defer.
func (e *liveEngine) close() {
	if e != nil {
		e.Close()
	}
}
