// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// CreateAgentRequest mirrors POST /api/v1/agents body (subset used by CLI).
type CreateAgentRequest struct {
	Name               string              `json:"name"`
	Namespace          string              `json:"namespace"`
	Protocol           string              `json:"protocol,omitempty"`
	Framework          string              `json:"framework,omitempty"`
	WorkloadType       string              `json:"workloadType,omitempty"`
	DeploymentMethod   string              `json:"deploymentMethod"`
	GitURL             string              `json:"gitUrl,omitempty"`
	GitPath            string              `json:"gitPath,omitempty"`
	GitBranch          string              `json:"gitBranch,omitempty"`
	ImageTag           string              `json:"imageTag,omitempty"`
	RegistryURL        *string             `json:"registryUrl,omitempty"`
	RegistrySecret     *string             `json:"registrySecret,omitempty"`
	StartCommand       *string             `json:"startCommand,omitempty"`
	ContainerImage     string              `json:"containerImage,omitempty"`
	ImagePullSecret    *string             `json:"imagePullSecret,omitempty"`
	CreateHTTPRoute    bool                `json:"createHttpRoute"`
	AuthBridgeEnabled  *bool               `json:"authBridgeEnabled,omitempty"`
	SpireEnabled       *bool               `json:"spireEnabled,omitempty"`
	ShipwrightConfig   *ShipwrightConfigJSON `json:"shipwrightConfig,omitempty"`
	ServicePorts       []ServicePortJSON     `json:"servicePorts,omitempty"`
}

// ShipwrightConfigJSON optional Shipwright overrides for source builds.
type ShipwrightConfigJSON struct {
	BuildStrategy *string  `json:"buildStrategy,omitempty"`
	Dockerfile    string   `json:"dockerfile,omitempty"`
	BuildArgs     []string `json:"buildArgs,omitempty"`
	BuildTimeout  string   `json:"buildTimeout,omitempty"`
}

// ServicePortJSON mirrors API service port.
type ServicePortJSON struct {
	Name       string `json:"name"`
	Port       int    `json:"port"`
	TargetPort int    `json:"targetPort"`
	Protocol   string `json:"protocol"`
}

// CreateAgentResponse mirrors API after create.
type CreateAgentResponse struct {
	Success   bool   `json:"success"`
	Name      string `json:"name"`
	Namespace string `json:"namespace"`
	Message   string `json:"message"`
}

func postJSON(ctx context.Context, baseURL, path, bearer string, body any) ([]byte, int, error) {
	baseURL = strings.TrimRight(baseURL, "/")
	u, err := url.Parse(baseURL + path)
	if err != nil {
		return nil, 0, err
	}
	var buf bytes.Buffer
	if body != nil {
		enc := json.NewEncoder(&buf)
		if err := enc.Encode(body); err != nil {
			return nil, 0, err
		}
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u.String(), &buf)
	if err != nil {
		return nil, 0, err
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")

	cli := &http.Client{Timeout: 120 * time.Second}
	res, err := tracedDo(req, cli)
	if err != nil {
		return nil, 0, err
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(res.Body)
	if err != nil {
		return nil, res.StatusCode, err
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return nil, res.StatusCode, fmt.Errorf("HTTP %d: %s", res.StatusCode, strings.TrimSpace(string(raw)))
	}
	return raw, res.StatusCode, nil
}

// CreateAgent POST /api/v1/agents (operator role).
func CreateAgent(ctx context.Context, baseURL, bearer string, req *CreateAgentRequest) (*CreateAgentResponse, error) {
	raw, _, err := postJSON(ctx, baseURL, "/api/v1/agents", bearer, req)
	if err != nil {
		return nil, err
	}
	var out CreateAgentResponse
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("decode create agent: %w", err)
	}
	return &out, nil
}

// AgentShipwrightBuildInfoResponse mirrors GET .../shipwright-build-info.
type AgentShipwrightBuildInfoResponse struct {
	Name                   string `json:"name"`
	Namespace              string `json:"namespace"`
	BuildRegistered        bool   `json:"buildRegistered"`
	BuildReason            string `json:"buildReason,omitempty"`
	BuildMessage           string `json:"buildMessage,omitempty"`
	OutputImage            string `json:"outputImage"`
	Strategy               string `json:"strategy"`
	GitURL                 string `json:"gitUrl"`
	GitRevision            string `json:"gitRevision"`
	ContextDir             string `json:"contextDir"`
	HasBuildRun            bool   `json:"hasBuildRun"`
	BuildRunName           string `json:"buildRunName,omitempty"`
	BuildRunPhase          string `json:"buildRunPhase,omitempty"`
	BuildRunStartTime      string `json:"buildRunStartTime,omitempty"`
	BuildRunCompletionTime string `json:"buildRunCompletionTime,omitempty"`
	BuildRunOutputImage    string `json:"buildRunOutputImage,omitempty"`
	BuildRunOutputDigest   string `json:"buildRunOutputDigest,omitempty"`
	BuildRunFailureMessage string `json:"buildRunFailureMessage,omitempty"`
}

// GetAgentShipwrightBuildInfo GET /api/v1/agents/{ns}/{name}/shipwright-build-info.
func GetAgentShipwrightBuildInfo(ctx context.Context, baseURL, bearer, namespace, name string) (*AgentShipwrightBuildInfoResponse, error) {
	path := fmt.Sprintf("/api/v1/agents/%s/%s/shipwright-build-info", url.PathEscape(namespace), url.PathEscape(name))
	body, _, err := getJSON(ctx, baseURL, path, nil, bearer)
	if err != nil {
		return nil, err
	}
	var out AgentShipwrightBuildInfoResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode build info: %w", err)
	}
	return &out, nil
}

// FinalizeShipwrightBuildRequest optional overrides for finalize (usually {}).
type FinalizeShipwrightBuildRequest struct {
	Protocol          *string             `json:"protocol,omitempty"`
	Framework         *string             `json:"framework,omitempty"`
	CreateHTTPRoute   *bool               `json:"createHttpRoute,omitempty"`
	AuthBridgeEnabled *bool               `json:"authBridgeEnabled,omitempty"`
	ImagePullSecret   *string             `json:"imagePullSecret,omitempty"`
	ServicePorts      []ServicePortJSON   `json:"servicePorts,omitempty"`
}

// FinalizeAgentShipwrightBuild POST .../finalize-shipwright-build.
func FinalizeAgentShipwrightBuild(ctx context.Context, baseURL, bearer, namespace, name string, body *FinalizeShipwrightBuildRequest) (*CreateAgentResponse, error) {
	path := fmt.Sprintf("/api/v1/agents/%s/%s/finalize-shipwright-build", url.PathEscape(namespace), url.PathEscape(name))
	if body == nil {
		body = &FinalizeShipwrightBuildRequest{}
	}
	raw, _, err := postJSON(ctx, baseURL, path, bearer, body)
	if err != nil {
		return nil, err
	}
	var out CreateAgentResponse
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("decode finalize: %w", err)
	}
	return &out, nil
}

// ClusterBuildStrategyInfo one strategy.
type ClusterBuildStrategyInfo struct {
	Name        string `json:"name"`
	Description string `json:"description,omitempty"`
}

// ClusterBuildStrategiesResponse GET /api/v1/agents/build-strategies.
type ClusterBuildStrategiesResponse struct {
	Strategies []ClusterBuildStrategyInfo `json:"strategies"`
}

// AgentShipwrightBuildSummary one Build CR for agent source builds.
type AgentShipwrightBuildSummary struct {
	Name                string `json:"name"`
	Namespace           string `json:"namespace"`
	Registered          bool   `json:"registered"`
	Strategy            string `json:"strategy"`
	GitURL              string `json:"gitUrl"`
	GitRevision         string `json:"gitRevision"`
	ContextDir          string `json:"contextDir"`
	OutputImage         string `json:"outputImage"`
	CreationTimestamp   string `json:"creationTimestamp,omitempty"`
}

// AgentShipwrightBuildListResponse GET /api/v1/agents/shipwright-builds.
type AgentShipwrightBuildListResponse struct {
	Items []AgentShipwrightBuildSummary `json:"items"`
}

// ListAgentShipwrightBuilds lists agent Shipwright Builds in one namespace or all enabled namespaces.
func ListAgentShipwrightBuilds(ctx context.Context, baseURL, bearer, namespace string, allNamespaces bool) (*AgentShipwrightBuildListResponse, error) {
	q := url.Values{}
	if allNamespaces {
		q.Set("allNamespaces", "true")
	} else {
		q.Set("namespace", namespace)
	}
	body, _, err := getJSON(ctx, baseURL, "/api/v1/agents/shipwright-builds", q, bearer)
	if err != nil {
		return nil, err
	}
	var out AgentShipwrightBuildListResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode shipwright builds: %w", err)
	}
	return &out, nil
}

// ListAgentBuildStrategies GET /api/v1/agents/build-strategies.
func ListAgentBuildStrategies(ctx context.Context, baseURL, bearer string) (*ClusterBuildStrategiesResponse, error) {
	body, _, err := getJSON(ctx, baseURL, "/api/v1/agents/build-strategies", nil, bearer)
	if err != nil {
		return nil, err
	}
	var out ClusterBuildStrategiesResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("decode strategies: %w", err)
	}
	return &out, nil
}
