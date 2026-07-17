package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Release location. Overridable via env so tests can point at a mock server.
const defaultSlug = "aslom/kagenti"

func updateBaseURL() string {
	if v := os.Getenv("ROSSOCTL_UPDATE_BASE"); v != "" {
		return strings.TrimRight(v, "/")
	}
	return "https://github.com"
}

func updateSlug() string {
	if v := os.Getenv("ROSSOCTL_UPDATE_SLUG"); v != "" {
		return v
	}
	return defaultSlug
}

func configDir() string {
	if v := os.Getenv("ROSSOCTL_CONFIG_DIR"); v != "" {
		return v
	}
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		home, _ := os.UserHomeDir()
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, "rossoctl")
}

func isDevBuild() bool { return version == "dev" || version == "" }

func stdoutIsTTY() bool {
	fi, err := os.Stdout.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}

// latestVersion does a HEAD on <base>/<slug>/releases/latest and reads the
// redirect Location to extract the tag. This avoids the rate-limited GitHub API
// (60 req/hr unauthenticated) — the recommended check for per-machine updaters.
func latestVersion(ctx context.Context) (string, error) {
	url := fmt.Sprintf("%s/%s/releases/latest", updateBaseURL(), updateSlug())
	req, err := http.NewRequestWithContext(ctx, http.MethodHead, url, nil)
	if err != nil {
		return "", err
	}
	client := &http.Client{
		// Don't follow the redirect — we want to read Location ourselves.
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	loc := resp.Header.Get("Location")
	if loc == "" {
		return "", fmt.Errorf("no redirect from %s (status %d)", url, resp.StatusCode)
	}
	i := strings.LastIndex(loc, "/tag/")
	if i < 0 {
		return "", fmt.Errorf("unexpected latest-release URL: %s", loc)
	}
	return strings.TrimPrefix(loc[i+len("/tag/"):], "v"), nil
}

// compareVersions returns -1, 0, 1 for a<b, a==b, a>b. Dotted-numeric, tolerant
// of a leading "v" and of pre-release/build suffixes (which it ignores).
func compareVersions(a, b string) int {
	pa, pb := parseVer(a), parseVer(b)
	n := len(pa)
	if len(pb) > n {
		n = len(pb)
	}
	for i := 0; i < n; i++ {
		var x, y int
		if i < len(pa) {
			x = pa[i]
		}
		if i < len(pb) {
			y = pb[i]
		}
		if x < y {
			return -1
		}
		if x > y {
			return 1
		}
	}
	return 0
}

func parseVer(s string) []int {
	s = strings.TrimPrefix(strings.TrimSpace(s), "v")
	if i := strings.IndexAny(s, "-+"); i >= 0 {
		s = s[:i]
	}
	var out []int
	for _, p := range strings.Split(s, ".") {
		n, _ := strconv.Atoi(p)
		out = append(out, n)
	}
	return out
}

// managedInstall reports whether rossoctl was installed by a package manager
// that owns the binary; self-update should defer to it rather than overwrite.
func managedInstall() (string, bool) {
	exe, err := os.Executable()
	if err != nil {
		return "", false
	}
	if resolved, err := filepath.EvalSymlinks(exe); err == nil {
		exe = resolved
	}
	low := strings.ToLower(exe)
	switch {
	case strings.Contains(low, "/cellar/"), strings.Contains(low, "/homebrew/"):
		return "Homebrew (run 'brew upgrade rossoctl')", true
	case strings.Contains(low, "/scoop/"):
		return "Scoop (run 'scoop update rossoctl')", true
	}
	return "", false
}

// maybeNotifyUpdate prints ONE stderr line if a newer release exists — at most
// once per 24h, and only when it's safe/useful: not a dev build, not opted out,
// not in CI, and stdout is a TTY. Never mutates the binary.
func maybeNotifyUpdate() {
	if isDevBuild() ||
		os.Getenv("ROSSOCTL_NO_UPDATE_CHECK") == "1" ||
		os.Getenv("CI") != "" ||
		!stdoutIsTTY() {
		return
	}
	stamp := filepath.Join(configDir(), "last-update-check")
	if fi, err := os.Stat(stamp); err == nil && time.Since(fi.ModTime()) < 24*time.Hour {
		return
	}
	// Record the attempt up front so a slow/failed check doesn't hammer.
	_ = os.MkdirAll(configDir(), 0o755)
	_ = os.WriteFile(stamp, []byte(time.Now().UTC().Format(time.RFC3339)), 0o644)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	latest, err := latestVersion(ctx)
	if err != nil {
		return
	}
	if compareVersions(latest, version) > 0 {
		fmt.Fprintf(os.Stderr,
			"rossoctl %s available (you have %s) — run 'rossoctl self-update'\n",
			latest, version)
	}
}

func cmdSelfUpdate(args []string) error {
	fs := flag.NewFlagSet("self-update", flag.ExitOnError)
	check := fs.Bool("check", false, "only report whether an update is available")
	dryRun := fs.Bool("dry-run", false, "show what would happen without replacing the binary")
	pin := fs.String("version", "", "install a specific version (e.g. v0.3.1)")
	if err := fs.Parse(args); err != nil {
		return err
	}

	if name, ok := managedInstall(); ok {
		fmt.Printf("rossoctl was installed via %s — update through it, not self-update.\n", name)
		return nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	target := strings.TrimPrefix(*pin, "v")
	if target == "" {
		l, err := latestVersion(ctx)
		if err != nil {
			return fmt.Errorf("checking for updates: %w", err)
		}
		target = l
	}

	cmp := compareVersions(target, version)

	if *check {
		if cmp > 0 {
			fmt.Printf("update available: %s (current %s)\n", target, version)
		} else {
			fmt.Printf("up to date: %s\n", version)
		}
		return nil
	}

	if cmp <= 0 && *pin == "" {
		fmt.Printf("already up to date: %s\n", version)
		return nil
	}

	exe, _ := os.Executable()
	if resolved, err := filepath.EvalSymlinks(exe); err == nil {
		exe = resolved
	}

	if *dryRun {
		fmt.Printf("[dry-run] would update rossoctl %s -> %s\n", version, target)
		fmt.Printf("[dry-run]   asset: %s/%s/releases/download/v%s/rossoctl_<os>_<arch>.tar.gz\n",
			updateBaseURL(), updateSlug(), target)
		fmt.Printf("[dry-run]   verify: checksums.txt, then atomic replace of %s\n", exe)
		return nil
	}

	// Production would: download the os/arch asset to a temp file, verify against
	// checksums.txt (and a signature), then atomically rename it over `exe`
	// (on Windows: rename running exe -> .old, write new, delete .old next start).
	// This stub does not ship real release binaries, so it stops here.
	return fmt.Errorf(
		"binary self-replacement is not implemented in this stub.\n"+
			"  Use 'rossoctl self-update --check' / '--dry-run', or reinstall:\n"+
			"    go install github.com/aslom/kagenti/scripts/rossoctl@v%s", target)
}
