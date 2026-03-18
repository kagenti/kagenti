// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package discover

import (
	"testing"
)

func TestParseMode(t *testing.T) {
	tests := []struct {
		in string
		want Mode
	}{
		{"", Auto},
		{"auto", Auto},
		{"AUTO", Auto},
		{"route", RouteOnly},
		{"service", ServiceOnly},
	}
	for _, tt := range tests {
		if got := ParseMode(tt.in); got != tt.want {
			t.Errorf("ParseMode(%q) = %v, want %v", tt.in, got, tt.want)
		}
	}
}
