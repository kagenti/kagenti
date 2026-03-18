// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestSetLogLevel(t *testing.T) {
	SetLogLevel(0)
	if LogLevel() != 0 {
		t.Fatal()
	}
	SetLogLevel(9)
	if LogLevel() != 9 {
		t.Fatal()
	}
	SetLogLevel(0)
}

func TestListAgents(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents" {
			http.NotFound(w, r)
			return
		}
		if r.URL.Query().Get("namespace") != "team1" {
			t.Errorf("namespace query: %q", r.URL.Query().Get("namespace"))
		}
		if r.Header.Get("Authorization") != "Bearer tok" {
			t.Errorf("missing bearer")
		}
		_, _ = w.Write([]byte(`{"items":[{"name":"a","namespace":"team1","description":"d","status":"Ready","labels":{}}]}`))
	}))
	defer srv.Close()

	out, err := ListAgents(context.Background(), srv.URL, "tok", "team1")
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Items) != 1 || out.Items[0].Name != "a" {
		t.Fatalf("%+v", out)
	}
}

func TestListNamespaces(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/namespaces" {
			http.NotFound(w, r)
			return
		}
		if r.URL.Query().Get("enabled_only") != "false" {
			t.Errorf("expected enabled_only=false for -A-style listing, got %q", r.URL.RawQuery)
		}
		_, _ = w.Write([]byte(`{"namespaces":["team1","team2"]}`))
	}))
	defer srv.Close()

	out, err := ListNamespaces(context.Background(), srv.URL, "tok", false)
	if err != nil {
		t.Fatal(err)
	}
	if len(out.Namespaces) != 2 {
		t.Fatalf("%+v", out)
	}
}

func TestListNamespacesEnabledOnlyOmitsQuery(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.RawQuery != "" {
			t.Errorf("enabled_only=true should omit query, got %q", r.URL.RawQuery)
		}
		_, _ = w.Write([]byte(`{"namespaces":["x"]}`))
	}))
	defer srv.Close()
	_, err := ListNamespaces(context.Background(), srv.URL, "tok", true)
	if err != nil {
		t.Fatal(err)
	}
}

func TestGetAgent(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents/ns1/my-agent" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(`{"metadata":{"name":"my-agent","namespace":"ns1"},"readyStatus":"Ready"}`))
	}))
	defer srv.Close()

	body, err := GetAgent(context.Background(), srv.URL, "tok", "ns1", "my-agent")
	if err != nil {
		t.Fatal(err)
	}
	if string(body) == "" {
		t.Fatal("empty body")
	}
}
