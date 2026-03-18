// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import "testing"

func TestValidateOutput(t *testing.T) {
	for _, o := range []string{"", "json", "yaml", "wide"} {
		if err := validateOutput(o); err != nil {
			t.Errorf("%q: %v", o, err)
		}
	}
	if err := validateOutput("table"); err == nil {
		t.Fatal("expected error")
	}
}
