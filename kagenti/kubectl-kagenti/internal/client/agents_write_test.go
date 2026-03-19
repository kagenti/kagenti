// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCreateAgentImage(t *testing.T) {
	var gotBody string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents" || r.Method != http.MethodPost {
			http.NotFound(w, r)
			return
		}
		b, _ := io.ReadAll(r.Body)
		gotBody = string(b)
		if r.Header.Get("Authorization") != "Bearer tok" {
			t.Error("missing bearer")
		}
		_, _ = w.Write([]byte(`{"success":true,"name":"a","namespace":"n","message":"ok"}`))
	}))
	defer srv.Close()

	req := &CreateAgentRequest{
		Name:             "a",
		Namespace:        "n",
		DeploymentMethod: "image",
		ContainerImage:   "img:v1",
	}
	out, err := CreateAgent(context.Background(), srv.URL, "tok", req)
	if err != nil {
		t.Fatal(err)
	}
	if !out.Success || out.Message != "ok" {
		t.Fatalf("%+v", out)
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(gotBody), &m); err != nil {
		t.Fatal(err)
	}
	if m["deploymentMethod"] != "image" || m["containerImage"] != "img:v1" {
		t.Fatalf("body: %s", gotBody)
	}
}

func TestCreateAgentSource(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		if !strings.Contains(string(b), `"gitUrl":"https://x`) {
			t.Errorf("expected gitUrl in body: %s", b)
		}
		_, _ = w.Write([]byte(`{"success":true,"name":"b","namespace":"n","message":"build started"}`))
	}))
	defer srv.Close()

	_, err := CreateAgent(context.Background(), srv.URL, "tok", &CreateAgentRequest{
		Name:             "b",
		Namespace:        "n",
		DeploymentMethod: "source",
		GitURL:           "https://x",
		GitBranch:        "main",
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestListAgentBuildStrategies(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents/build-strategies" {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(`{"strategies":[{"name":"buildah","description":"d"}]}`))
	}))
	defer srv.Close()

	out, err := ListAgentBuildStrategies(context.Background(), srv.URL, "tok")
	if err != nil || len(out.Strategies) != 1 || out.Strategies[0].Name != "buildah" {
		t.Fatalf("%+v %v", out, err)
	}
}

func TestListAgentShipwrightBuilds(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents/shipwright-builds" {
			http.NotFound(w, r)
			return
		}
		if r.URL.Query().Get("namespace") != "n1" {
			t.Errorf("query: %q", r.URL.RawQuery)
		}
		_, _ = w.Write([]byte(`{"items":[{"name":"b1","namespace":"n1","registered":true,"strategy":"buildah","gitUrl":"https://g","outputImage":"i:1"}]}`))
	}))
	defer srv.Close()

	out, err := ListAgentShipwrightBuilds(context.Background(), srv.URL, "tok", "n1", false)
	if err != nil || len(out.Items) != 1 || out.Items[0].Name != "b1" {
		t.Fatalf("%+v %v", out, err)
	}
}

func TestListAgentShipwrightBuildsAllNS(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("allNamespaces") != "true" {
			t.Errorf("expected allNamespaces=true")
		}
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer srv.Close()
	_, err := ListAgentShipwrightBuilds(context.Background(), srv.URL, "tok", "", true)
	if err != nil {
		t.Fatal(err)
	}
}

func TestFinalizeAgentShipwrightBuild(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents/ns1/ag1/finalize-shipwright-build" || r.Method != http.MethodPost {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(`{"success":true,"name":"ag1","namespace":"ns1","message":"done"}`))
	}))
	defer srv.Close()

	out, err := FinalizeAgentShipwrightBuild(context.Background(), srv.URL, "tok", "ns1", "ag1", nil)
	if err != nil || !out.Success {
		t.Fatalf("%+v %v", out, err)
	}
}
