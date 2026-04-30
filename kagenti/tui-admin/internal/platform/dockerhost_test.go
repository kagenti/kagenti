package platform

import (
	"testing"
)

func TestIsIPv4(t *testing.T) {
	t.Parallel()
	tests := []struct {
		input string
		want  bool
	}{
		{"192.168.1.1", true},
		{"10.0.0.1", true},
		{"172.18.0.1", true},
		{"0.0.0.0", true},
		{"255.255.255.255", true},
		{"", false},
		{"abc", false},
		{"192.168.1", false},
		{"192.168.1.1.1", false},
		{"::1", false},
	}
	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			t.Parallel()
			if got := isIPv4(tt.input); got != tt.want {
				t.Errorf("isIPv4(%q) = %v, want %v", tt.input, got, tt.want)
			}
		})
	}
}

func TestRandomInt(t *testing.T) {
	t.Parallel()
	a := randomInt()
	b := randomInt()
	// They should be different (very high probability with nanosecond precision)
	// but we just check they're in range
	if a < 0 || a >= 100000 {
		t.Errorf("randomInt out of range: %d", a)
	}
	_ = b
}
