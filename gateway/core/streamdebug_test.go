package core

import (
	"net/url"
	"strings"
	"testing"
)

func TestSanitizeStreamQuery_RedactsUnknownAndLongValues(t *testing.T) {
	q, _ := url.ParseQuery("language=en&codec=opus&preview=cloud&key=s3cr3t-value&token=abc&model=" + strings.Repeat("x", 80))
	got := sanitizeStreamQuery(q)
	for _, leak := range []string{"s3cr3t", "abc", strings.Repeat("x", 80)} {
		if strings.Contains(got, leak) {
			t.Fatalf("leaked %q in %q", leak, got)
		}
	}
	for _, want := range []string{"codec=opus", "language=en", "preview=cloud", "key=<redacted 12 chars>", "token=<redacted 3 chars>", "model=<redacted 80 chars>"} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in %q", want, got)
		}
	}
}

func TestSanitizeStreamQuery_Empty(t *testing.T) {
	if got := sanitizeStreamQuery(url.Values{}); got != "(none)" {
		t.Fatalf("got %q", got)
	}
}
