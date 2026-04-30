// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"bytes"
	"strings"
	"testing"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
)

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

func TestWriteAgentListTable(t *testing.T) {
	var buf bytes.Buffer
	items := []client.AgentSummary{
		{Name: "x", Namespace: "n1", Status: "Ready", WorkloadType: "deployment"},
	}
	if err := writeAgentList(&buf, "", items, true); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(buf.String(), "x") || !strings.Contains(buf.String(), "n1") {
		t.Fatal(buf.String())
	}
}

func TestWriteToolListJSON(t *testing.T) {
	var buf bytes.Buffer
	items := []client.ToolSummary{{Name: "t1", Namespace: "n1", Status: "Ready"}}
	if err := writeToolList(&buf, "json", items, false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(buf.String(), "t1") {
		t.Fatal(buf.String())
	}
}
