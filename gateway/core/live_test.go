package core

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/coder/websocket"
)

// --- synthetic audio ---

// pcmPattern renders alternating speech-like tone and quiet noise. Each entry is a
// duration in ms; even indexes are tone, odd ones are pauses.
func pcmPattern(ms ...int) []byte {
	rng := rand.New(rand.NewSource(1))
	var buf bytes.Buffer
	n := 0
	for i, d := range ms {
		for s := 0; s < d*liveSampleRate/1000; s++ {
			v := rng.NormFloat64() * 32768 * math.Pow(10, -55.0/20) // noise floor
			if i%2 == 0 {
				v += 0.1 * 32768 * math.Sin(2*math.Pi*220*float64(n)/liveSampleRate) // ~-23 dBFS
			}
			n++
			binary.Write(&buf, binary.LittleEndian, int16(v)) //nolint:errcheck
		}
	}
	return buf.Bytes()
}

func testLiveConfig() LiveConfig {
	return LiveConfig{Segmented: true, PauseMs: 700, MinSegMs: 3000, MaxSegMs: 20000, ShortPauseMs: 300, PartialEveryMs: 100}
}

// feedLive feeds pcm in 100 ms writes and lets the worker drain after each one, like
// audio arriving in real time (audio that arrives all at once folds pending cuts into
// the tail, which is correct but makes the request count timing-dependent).
func feedLive(t *testing.T, e *liveEngine, pcm []byte) {
	t.Helper()
	for len(pcm) > 0 {
		n := 3200
		if n > len(pcm) {
			n = len(pcm)
		}
		e.Write(pcm[:n]) //nolint:errcheck
		pcm = pcm[n:]
		deadline := time.Now().Add(5 * time.Second)
		for {
			e.mu.Lock()
			idle := len(e.pending) == 0 && !e.busy
			e.mu.Unlock()
			if idle || time.Now().After(deadline) {
				break
			}
			time.Sleep(time.Millisecond)
		}
	}
}

// --- pause detector ---

func TestPauseDetector_CutsOnlyAtLongPauses(t *testing.T) {
	d := pauseDetector{cfg: testLiveConfig()}
	// 4 s speech, 0.3 s gap (too short), 2 s speech, 1 s gap (cut), 4 s speech.
	pcm := pcmPattern(4000, 300, 2000, 1000, 4000)
	var cuts []liveCut
	for i := 0; i < len(pcm); i += 682 { // odd chunk size, like the app's PCM frames
		end := i + 682
		if end > len(pcm) {
			end = len(pcm)
		}
		cuts = append(cuts, d.push(pcm[i:end])...)
	}
	if len(cuts) != 1 {
		t.Fatalf("want 1 cut, got %d: %+v", len(cuts), cuts)
	}
	at := float64(cuts[0].at) / liveSampleRate
	if at < 6.3 || at > 7.3 {
		t.Fatalf("cut at %.2fs, want inside the 6.3-7.3 s pause", at)
	}
}

func TestPauseDetector_RespectsMinSegment(t *testing.T) {
	d := pauseDetector{cfg: testLiveConfig()}
	// 1 s speech then a long pause: shorter than MinSegMs, so no cut yet.
	if cuts := d.push(pcmPattern(1000, 1500)); len(cuts) != 0 {
		t.Fatalf("want no cut, got %+v", cuts)
	}
}

func TestPauseDetector_ShortPauseAfterMaxSegment(t *testing.T) {
	cfg := testLiveConfig()
	cfg.MaxSegMs = 5000
	d := pauseDetector{cfg: cfg}
	// 6 s speech, then a 400 ms pause: past MaxSegMs the 300 ms short pause is enough.
	if cuts := d.push(pcmPattern(6000, 400, 1000)); len(cuts) != 1 {
		t.Fatalf("want 1 cut, got %+v", cuts)
	}
}

// --- engine ---

type fakeASR struct {
	mu    sync.Mutex
	calls []float64 // seconds of audio per call
	fail  func(call int) error
	delay time.Duration
}

func (f *fakeASR) transcribe(ctx context.Context, wav []byte) (string, error) {
	f.mu.Lock()
	call := len(f.calls)
	f.calls = append(f.calls, float64(len(wav)-44)/2/liveSampleRate)
	fail := f.fail
	f.mu.Unlock()
	if f.delay > 0 {
		select {
		case <-time.After(f.delay):
		case <-ctx.Done():
			return "", ctx.Err()
		}
	}
	if fail != nil {
		if err := fail(call); err != nil {
			return "", err
		}
	}
	return fmt.Sprintf("part%d.", call+1), nil
}

func (f *fakeASR) durations() []float64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]float64(nil), f.calls...)
}

func TestLiveEngine_SegmentsInBackgroundAndJoins(t *testing.T) {
	asr := &fakeASR{}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, nil)
	defer e.Close()
	feedLive(t, e, pcmPattern(4000, 1000, 4000, 1000, 2000))
	text, ok, st := e.Finish(context.Background())
	if !ok {
		t.Fatal("Finish not ok")
	}
	if text != "part1. part2. part3." {
		t.Fatalf("text = %q", text)
	}
	d := asr.durations()
	if len(d) != 3 || st.segments != 2 {
		t.Fatalf("calls %v, segments %d", d, st.segments)
	}
	// The tail (last request) is short: only the audio after the second pause.
	if d[2] > 3.0 {
		t.Fatalf("tail was %.2fs, want < 3 s", d[2])
	}
	if total := d[0] + d[1] + d[2]; math.Abs(total-12.0) > 0.05 {
		t.Fatalf("segments cover %.2fs of 12 s", total)
	}
}

func TestLiveEngine_SilentTailIsSkipped(t *testing.T) {
	asr := &fakeASR{}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, nil)
	defer e.Close()
	feedLive(t, e, pcmPattern(4000, 1500))
	text, ok, _ := e.Finish(context.Background())
	if !ok || text != "part1." {
		t.Fatalf("got %q ok=%v", text, ok)
	}
	if n := len(asr.durations()); n != 1 {
		t.Fatalf("want 1 request (no tail), got %d", n)
	}
}

func TestLiveEngine_SegmentFailureMeansFallback(t *testing.T) {
	asr := &fakeASR{fail: func(call int) error {
		if call == 0 {
			return errors.New("backend returned 500: secret words")
		}
		return nil
	}}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, nil)
	defer e.Close()
	feedLive(t, e, pcmPattern(4000, 1000, 2000))
	if _, ok, _ := e.Finish(context.Background()); ok {
		t.Fatal("Finish ok after a failed segment; want fallback")
	}
}

func TestLiveEngine_TailFailureMeansFallback(t *testing.T) {
	asr := &fakeASR{fail: func(call int) error {
		if call == 1 {
			return errors.New("boom")
		}
		return nil
	}}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, nil)
	defer e.Close()
	feedLive(t, e, pcmPattern(4000, 1000, 2000))
	if _, ok, _ := e.Finish(context.Background()); ok {
		t.Fatal("Finish ok after a failed tail; want fallback")
	}
}

func TestLiveEngine_NoSpeechMeansFallback(t *testing.T) {
	asr := &fakeASR{}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, nil)
	defer e.Close()
	feedLive(t, e, pcmPattern(0, 3000))
	if _, ok, _ := e.Finish(context.Background()); ok {
		t.Fatal("Finish ok with no speech; want the whole clip to decide")
	}
}

func TestLiveEngine_WaitsForInFlightSegment(t *testing.T) {
	asr := &fakeASR{delay: 150 * time.Millisecond}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, nil)
	defer e.Close()
	feedLive(t, e, pcmPattern(4000, 1000, 2000))
	text, ok, _ := e.Finish(context.Background())
	if !ok || text != "part1. part2." {
		t.Fatalf("got %q ok=%v", text, ok)
	}
}

func TestLiveEngine_PartialsCarryWholeTranscript(t *testing.T) {
	asr := &fakeASR{}
	e := newLiveEngine(context.Background(), testLiveConfig(), asr.transcribe, asr.transcribe)
	defer e.Close()
	var got []string
	done := make(chan struct{})
	go func() {
		defer close(done)
		for s := range e.interims {
			got = append(got, s)
		}
	}()
	pcm := pcmPattern(4000, 1000, 3000)
	for i := 0; i < len(pcm); i += 6400 { // 200 ms per write, paced
		end := i + 6400
		if end > len(pcm) {
			end = len(pcm)
		}
		e.Write(pcm[i:end]) //nolint:errcheck
		time.Sleep(5 * time.Millisecond)
	}
	time.Sleep(50 * time.Millisecond)
	e.stopInterims()
	<-done
	if len(got) == 0 {
		t.Fatal("no interims")
	}
	for _, s := range got {
		if s == "" {
			t.Fatal("empty interim")
		}
	}
	// The engine outlives its interims: the segmented final still works.
	if _, ok, _ := e.Finish(context.Background()); !ok {
		t.Fatal("Finish after interims not ok")
	}
}

// --- handler ---

// segmentBackend answers every request with a counter; fail(n) can make call n fail.
func segmentBackend(t *testing.T, fail func(n int) bool) (*httptest.Server, *int32, *atomic.Value) {
	t.Helper()
	var n int32
	var lastName atomic.Value
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		call := int(atomic.AddInt32(&n, 1))
		r.ParseMultipartForm(50 << 20) //nolint:errcheck
		if _, fh, err := r.FormFile("file"); err == nil {
			lastName.Store(fh.Filename)
		}
		if fail != nil && fail(call) {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"text":"r%d"}`, call)
	}))
	t.Cleanup(srv.Close)
	return srv, &n, &lastName
}

func liveGateway(t *testing.T, backendURL string, cfg LiveConfig) *httptest.Server {
	t.Helper()
	g := makeGateway(backendURL, false, 50<<20)
	g.live = cfg
	srv := httptest.NewServer(g.StreamingHandler())
	t.Cleanup(srv.Close)
	return srv
}

// streamPCM sends pcm in 682-byte frames (like the app), then done; returns all text frames.
func streamPCM(t *testing.T, srv *httptest.Server, query string, pcm []byte, pace time.Duration) []string {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wsURL(srv, query), nil)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.CloseNow()
	var mu sync.Mutex
	var got []string
	readDone := make(chan struct{})
	go func() {
		defer close(readDone)
		for {
			typ, data, err := conn.Read(ctx)
			if err != nil {
				return
			}
			if typ == websocket.MessageText {
				mu.Lock()
				got = append(got, string(data))
				mu.Unlock()
			}
		}
	}()
	for i := 0; i < len(pcm); i += 682 {
		end := i + 682
		if end > len(pcm) {
			end = len(pcm)
		}
		if err := conn.Write(ctx, websocket.MessageBinary, pcm[i:end]); err != nil {
			t.Fatalf("write: %v", err)
		}
		if pace > 0 && (i/682)%25 == 0 {
			time.Sleep(pace)
		}
	}
	done, _ := json.Marshal(map[string]string{"action": "done"})
	conn.Write(ctx, websocket.MessageText, done) //nolint:errcheck
	<-readDone
	mu.Lock()
	defer mu.Unlock()
	return got
}

func lastResultText(t *testing.T, frames []string) string {
	t.Helper()
	if len(frames) == 0 {
		t.Fatal("no frames")
	}
	var r struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	json.Unmarshal([]byte(frames[len(frames)-1]), &r) //nolint:errcheck
	if r.Type != "" {
		t.Fatalf("last frame is %q, not a result: %v", r.Type, frames)
	}
	return r.Text
}

func TestStreaming_SegmentedFinal_PCM(t *testing.T) {
	backend, calls, _ := segmentBackend(t, nil)
	srv := liveGateway(t, backend.URL, testLiveConfig())
	frames := streamPCM(t, srv, "", pcmPattern(4000, 1000, 4000, 1000, 2000), 0)
	if got := lastResultText(t, frames); got != "r1 r2 r3" {
		t.Fatalf("final %q, want the three parts joined", got)
	}
	if n := atomic.LoadInt32(calls); n != 3 {
		t.Fatalf("backend calls = %d, want 3 (no whole-clip request)", n)
	}
}

func TestStreaming_SegmentedFinal_FallsBackToWholeClip(t *testing.T) {
	backend, calls, _ := segmentBackend(t, func(n int) bool { return n == 1 })
	srv := liveGateway(t, backend.URL, testLiveConfig())
	frames := streamPCM(t, srv, "", pcmPattern(4000, 1000, 2000), 0)
	// Call 1 (segment) failed, call 2 is the whole clip.
	if got := lastResultText(t, frames); got != "r2" {
		t.Fatalf("final %q, want the whole-clip answer", got)
	}
	if n := atomic.LoadInt32(calls); n != 2 {
		t.Fatalf("backend calls = %d, want 2", n)
	}
}

func TestStreaming_SegmentedFinal_OffByDefault(t *testing.T) {
	backend, calls, _ := segmentBackend(t, nil)
	srv := liveGateway(t, backend.URL, LiveConfig{})
	frames := streamPCM(t, srv, "", pcmPattern(4000, 1000, 4000, 1000, 2000), 0)
	if got := lastResultText(t, frames); got != "r1" {
		t.Fatalf("final %q", got)
	}
	if n := atomic.LoadInt32(calls); n != 1 {
		t.Fatalf("backend calls = %d, want 1", n)
	}
}

func TestStreaming_BuiltinPreview_InterimsThenResult(t *testing.T) {
	backend, _, _ := segmentBackend(t, nil)
	cfg := testLiveConfig()
	cfg.Segmented = false
	cfg.Preview = true
	srv := liveGateway(t, backend.URL, cfg)
	frames := streamPCM(t, srv, "preview=cloud", pcmPattern(4000, 1000, 3000), 20*time.Millisecond)
	interims := 0
	for i, f := range frames {
		var r struct{ Type, Text string }
		json.Unmarshal([]byte(f), &r) //nolint:errcheck
		if r.Type == "interim" {
			interims++
			if r.Text == "" {
				t.Fatal("empty interim")
			}
			if i == len(frames)-1 {
				t.Fatal("interim after the result")
			}
		}
	}
	if interims == 0 {
		t.Fatalf("no interim frames: %v", frames)
	}
	lastResultText(t, frames)
}

func TestStreaming_BuiltinPreview_IgnoredWithoutParam(t *testing.T) {
	backend, calls, _ := segmentBackend(t, nil)
	cfg := testLiveConfig()
	cfg.Segmented = false
	cfg.Preview = true
	srv := liveGateway(t, backend.URL, cfg)
	frames := streamPCM(t, srv, "", pcmPattern(4000, 1000, 3000), 20*time.Millisecond)
	if len(frames) != 1 || atomic.LoadInt32(calls) != 1 {
		t.Fatalf("frames %v calls %d: preview must stay off without ?preview=cloud", frames, atomic.LoadInt32(calls))
	}
}

func TestStreaming_SegmentedFinal_Opus(t *testing.T) {
	p := ensureFfmpeg(t)
	// 3 s tone, 1 s silence, repeated: two pauses to cut at.
	cmd := exec.Command(p, "-loglevel", "error", "-f", "lavfi",
		"-i", "aevalsrc=0.1*sin(2*PI*220*t)*lt(mod(t\\,4)\\,3):s=16000:d=10",
		"-c:a", "libopus", "-b:a", "16k", "-page_duration", "200000", "-f", "ogg", "pipe:1")
	var ogg bytes.Buffer
	cmd.Stdout = &ogg
	if err := cmd.Run(); err != nil {
		t.Skipf("libopus encode failed: %v", err)
	}
	backend, calls, lastName := segmentBackend(t, nil)
	srv := liveGateway(t, backend.URL, testLiveConfig())
	text, err := streamOpusBinary(t, srv, ogg.Bytes(), true)
	if err != nil {
		t.Fatal(err)
	}
	n := atomic.LoadInt32(calls)
	if n < 2 {
		t.Fatalf("backend calls = %d, want segments", n)
	}
	if want := fmt.Sprintf("r%d", n); !strings.HasSuffix(text, want) || strings.Count(text, "r") != int(n) {
		t.Fatalf("final %q after %d calls", text, n)
	}
	if name, _ := lastName.Load().(string); name != "audio.wav" {
		t.Fatalf("backend got %q, want decoded audio.wav", name)
	}
}
