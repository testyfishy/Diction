package core

import (
	"fmt"
	"log"
	"net/url"
	"sort"
	"strings"
	"time"
)

// DICTION_DEBUG_STREAM=true logs, per /v1/audio/stream session, what the client asked
// for and how its audio arrived: the query string, the offered and negotiated
// subprotocols, and frame timing. It never logs audio, transcripts, the context frame
// (custom words, cursor text) or any credential.

// streamQuerySafeKeys are query parameters whose values are logged as-is. Any other
// parameter is logged by name and value length only, so an unknown or future
// credential-bearing parameter cannot leak.
var streamQuerySafeKeys = map[string]bool{
	"language": true, "codec": true, "preview": true, "enhance": true,
	"split_enhance": true, "intent": true, "merge": true, "phones": true,
	"auto_edit": true, "model": true, "e2e": true, "sample_rate": true,
}

func sanitizeStreamQuery(q url.Values) string {
	keys := make([]string, 0, len(q))
	for k := range q {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		for _, v := range q[k] {
			if streamQuerySafeKeys[strings.ToLower(k)] && len(v) <= 64 {
				parts = append(parts, k+"="+v)
			} else {
				parts = append(parts, fmt.Sprintf("%s=<redacted %d chars>", k, len(v)))
			}
		}
	}
	if len(parts) == 0 {
		return "(none)"
	}
	return strings.Join(parts, "&")
}

// streamFrameStats tracks how the client's binary frames arrived.
type streamFrameStats struct {
	opened  time.Time
	first   time.Time
	last    time.Time
	frames  int
	bytes   int64
	minSize int
	maxSize int
	maxGap  time.Duration
}

func (s *streamFrameStats) add(n int) {
	now := time.Now()
	if s.frames == 0 {
		s.first = now
		s.minSize, s.maxSize = n, n
	} else if gap := now.Sub(s.last); gap > s.maxGap {
		s.maxGap = gap
	}
	if n < s.minSize {
		s.minSize = n
	}
	if n > s.maxSize {
		s.maxSize = n
	}
	s.last = now
	s.frames++
	s.bytes += int64(n)
}

func (s *streamFrameStats) logDone(codec string) {
	if s.frames == 0 {
		log.Printf("ws debug: done after %dms, no audio frames", time.Since(s.opened).Milliseconds())
		return
	}
	log.Printf("ws debug: done codec=%s frames=%d bytes=%d size=%d..%d first_frame_after=%dms span=%dms max_gap=%dms last_frame_to_done=%dms",
		codec, s.frames, s.bytes, s.minSize, s.maxSize,
		s.first.Sub(s.opened).Milliseconds(), s.last.Sub(s.first).Milliseconds(),
		s.maxGap.Milliseconds(), time.Since(s.last).Milliseconds())
}
