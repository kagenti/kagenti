// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"fmt"
	"net/http"
	"os"
	"sync/atomic"
	"time"
)

var logLevel atomic.Int32

// SetLogLevel sets global HTTP trace verbosity (used before API calls).
// Level 9 enables one line per request before send and one line after (or on error).
func SetLogLevel(n int) {
	if n < 0 {
		n = 0
	}
	logLevel.Store(int32(n))
}

// LogLevel returns the current log level.
func LogLevel() int {
	return int(logLevel.Load())
}

func tracedDo(req *http.Request, cli *http.Client) (*http.Response, error) {
	urlStr := req.URL.String()
	lvl := LogLevel()
	start := time.Now()
	if lvl >= 9 {
		_, _ = fmt.Fprintf(os.Stderr, "[kagenti] --> %s %s\n", req.Method, urlStr)
	}
	res, err := cli.Do(req)
	if lvl >= 9 {
		if err != nil {
			_, _ = fmt.Fprintf(os.Stderr, "[kagenti] <-- error after %v: %v\n    %s\n", time.Since(start), err, urlStr)
		} else {
			_, _ = fmt.Fprintf(os.Stderr, "[kagenti] <-- %d after %v\n    %s\n", res.StatusCode, time.Since(start), urlStr)
		}
	}
	return res, err
}
