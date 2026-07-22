package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestCompareVersions(t *testing.T) {
	cases := []struct {
		a, b string
		want int
	}{
		{"0.1.0", "0.1.0", 0},
		{"v0.1.0", "0.1.0", 0},
		{"0.1.0", "0.2.0", -1},
		{"0.2.0", "0.1.9", 1},
		{"1.0.0", "0.9.9", 1},
		{"0.10.0", "0.9.0", 1},    // numeric, not lexical
		{"1.2.3-rc1", "1.2.3", 0}, // pre-release suffix ignored
		{"2.0", "2.0.0", 0},
	}
	for _, c := range cases {
		if got := compareVersions(c.a, c.b); got != c.want {
			t.Errorf("compareVersions(%q,%q)=%d want %d", c.a, c.b, got, c.want)
		}
	}
}

func TestLatestVersion(t *testing.T) {
	// Mock the GitHub releases/latest redirect: HEAD returns 302 + Location.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/aslom/kagenti/releases/latest" {
			w.Header().Set("Location", "/aslom/kagenti/releases/tag/v9.9.9")
			w.WriteHeader(http.StatusFound)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	t.Setenv("ROSSOCTL_UPDATE_BASE", srv.URL)
	t.Setenv("ROSSOCTL_UPDATE_SLUG", "aslom/kagenti")

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	got, err := latestVersion(ctx)
	if err != nil {
		t.Fatalf("latestVersion error: %v", err)
	}
	if got != "9.9.9" {
		t.Fatalf("latestVersion = %q, want 9.9.9", got)
	}
	if compareVersions(got, "0.1.0") <= 0 {
		t.Fatalf("expected %q > 0.1.0", got)
	}
}

func TestParseVer(t *testing.T) {
	got := parseVer("v1.2.3-rc4")
	want := []int{1, 2, 3}
	if len(got) != len(want) {
		t.Fatalf("parseVer len=%d want %d (%v)", len(got), len(want), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("parseVer[%d]=%d want %d", i, got[i], want[i])
		}
	}
}
