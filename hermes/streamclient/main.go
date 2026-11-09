// streamclient speaks the Diction app's /v1/audio/stream protocol, for testing a
// gateway without the phone. It paces audio in real time, sends {"action":"done"},
// and prints one JSON line: time from done to the result, every interim frame with
// its time, and the final text.
//
//	streamclient -url ws://127.0.0.1:8081/v1/audio/stream -file clip.ogg            # Opus, like the app
//	streamclient -url ws://127.0.0.1:8081/v1/audio/stream -file clip.wav -preview   # PCM + live text
//
// A pairing key, if the gateway needs one, is read from DICTION_TEST_KEY and sent as a
// Bearer header. It is never printed.
package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/coder/websocket"
)

type interim struct {
	AtMs int64  `json:"at_ms"` // since the first audio frame
	Text string `json:"text"`
}

type report struct {
	File       string    `json:"file"`
	Codec      string    `json:"codec"`
	AudioMs    int64     `json:"audio_ms"`
	DoneToMs   int64     `json:"done_to_result_ms"`
	Subproto   string    `json:"subprotocol"`
	Interims   []interim `json:"interims,omitempty"`
	Final      string    `json:"final"`
	AfterFinal int       `json:"frames_after_final"`
	Error      string    `json:"error,omitempty"`
}

type chunk struct {
	data []byte
	at   time.Duration // when it may be sent, from the start
}

// oggPages splits an Ogg stream into pages, each due when its last sample was recorded.
func oggPages(b []byte) ([]chunk, time.Duration, error) {
	var out []chunk
	var end time.Duration
	for i := 0; i < len(b); {
		if i+27 > len(b) || string(b[i:i+4]) != "OggS" {
			return nil, 0, fmt.Errorf("bad ogg page at %d", i)
		}
		nseg := int(b[i+26])
		n := 27 + nseg
		for _, s := range b[i+27 : i+27+nseg] {
			n += int(s)
		}
		gp := int64(binary.LittleEndian.Uint64(b[i+6 : i+14]))
		at := time.Duration(0)
		if gp > 312 { // 312 = libopus pre-skip
			at = time.Duration(gp-312) * time.Second / 48000
		}
		out = append(out, chunk{data: b[i : i+n], at: at})
		end = at
		i += n
	}
	return out, end, nil
}

// pcmFrames reads a 16 kHz mono s16 WAV and cuts it into 20 ms frames.
func pcmFrames(b []byte) ([]chunk, time.Duration, error) {
	if len(b) < 44 || string(b[0:4]) != "RIFF" || string(b[8:12]) != "WAVE" {
		return nil, 0, fmt.Errorf("not a WAV")
	}
	i := 12
	var data []byte
	for i+8 <= len(b) {
		id, size := string(b[i:i+4]), int(binary.LittleEndian.Uint32(b[i+4:i+8]))
		if id == "fmt " && binary.LittleEndian.Uint32(b[i+12:i+16]) != 16000 {
			return nil, 0, fmt.Errorf("WAV must be 16 kHz")
		}
		if id == "data" {
			data = b[i+8 : min(len(b), i+8+size)]
			break
		}
		i += 8 + size
	}
	const frame = 640
	var out []chunk
	for off := 0; off < len(data); off += frame {
		e := min(off+frame, len(data))
		out = append(out, chunk{data: data[off:e], at: time.Duration(e/2) * time.Second / 16000})
	}
	return out, time.Duration(len(data)/2) * time.Second / 16000, nil
}

func main() {
	u := flag.String("url", "ws://127.0.0.1:8080/v1/audio/stream", "gateway stream URL (no query)")
	file := flag.String("file", "", ".ogg (sent as Opus) or .wav (sent as PCM)")
	preview := flag.Bool("preview", false, "ask for live text (?preview=cloud)")
	lang := flag.String("language", "en", "language query parameter")
	words := flag.String("words", "", "comma-separated My Words for the context frame")
	fast := flag.Bool("fast", false, "send audio as fast as possible instead of in real time")
	flag.Parse()

	r := report{File: *file}
	err := run(*u, *file, *preview, *lang, *words, *fast, &r)
	if err != nil {
		r.Error = err.Error()
	}
	out, _ := json.Marshal(r)
	fmt.Println(string(out))
	if err != nil {
		os.Exit(1)
	}
}

func run(base, file string, preview bool, lang, words string, fast bool, r *report) error {
	raw, err := os.ReadFile(file)
	if err != nil {
		return err
	}
	var chunks []chunk
	var dur time.Duration
	q := url.Values{"language": {lang}}
	opts := &websocket.DialOptions{HTTPHeader: http.Header{}}
	if strings.HasSuffix(file, ".ogg") {
		r.Codec = "opus"
		chunks, dur, err = oggPages(raw)
		q.Set("codec", "opus")
		opts.Subprotocols = []string{"diction.opus.v1"}
	} else {
		r.Codec = "pcm"
		chunks, dur, err = pcmFrames(raw)
	}
	if err != nil {
		return err
	}
	r.AudioMs = dur.Milliseconds()
	if preview {
		q.Set("preview", "cloud")
	}
	if k := os.Getenv("DICTION_TEST_KEY"); k != "" {
		opts.HTTPHeader.Set("Authorization", "Bearer "+k)
	}

	ctx, cancel := context.WithTimeout(context.Background(), dur+2*time.Minute)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, base+"?"+q.Encode(), opts)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer conn.CloseNow()
	conn.SetReadLimit(8 << 20)
	r.Subproto = conn.Subprotocol()
	if r.Codec == "opus" && r.Subproto != "diction.opus.v1" {
		return fmt.Errorf("server declined Opus")
	}

	if words != "" {
		var cw []map[string]string
		for _, w := range strings.Split(words, ",") {
			cw = append(cw, map[string]string{"word": strings.TrimSpace(w)})
		}
		ctxFrame, _ := json.Marshal(map[string]any{"customWords": cw})
		if err := conn.Write(ctx, websocket.MessageText, ctxFrame); err != nil {
			return err
		}
	}

	var mu sync.Mutex
	var doneAt time.Time
	start := time.Now()
	finalCh := make(chan error, 1)
	go func() {
		gotFinal := false
		for {
			_, data, err := conn.Read(ctx)
			if err != nil {
				if !gotFinal {
					finalCh <- fmt.Errorf("read: %w", err)
				}
				return
			}
			var f struct {
				Type, Text, Status string
			}
			json.Unmarshal(data, &f) //nolint:errcheck
			mu.Lock()
			switch {
			case gotFinal:
				r.AfterFinal++
			case f.Type == "interim":
				r.Interims = append(r.Interims, interim{AtMs: time.Since(start).Milliseconds(), Text: f.Text})
			case f.Type == "":
				gotFinal = true
				r.Final = f.Text
				r.DoneToMs = time.Since(doneAt).Milliseconds()
				finalCh <- nil
			}
			mu.Unlock()
		}
	}()

	for _, c := range chunks {
		if !fast {
			if d := time.Until(start.Add(c.at)); d > 0 {
				time.Sleep(d)
			}
		}
		if err := conn.Write(ctx, websocket.MessageBinary, c.data); err != nil {
			return fmt.Errorf("write audio: %w", err)
		}
	}
	done, _ := json.Marshal(map[string]string{"action": "done"})
	mu.Lock()
	doneAt = time.Now()
	mu.Unlock()
	if err := conn.Write(ctx, websocket.MessageText, done); err != nil {
		return fmt.Errorf("write done: %w", err)
	}
	if err := <-finalCh; err != nil {
		return err
	}
	time.Sleep(300 * time.Millisecond) // catch anything written after the result
	mu.Lock()
	defer mu.Unlock()
	return nil
}
