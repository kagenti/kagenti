// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"encoding/json"
	"fmt"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/kube"
	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

func deployCmd() *cobra.Command {
	var (
		image           string
		workloadType    string
		protocol        string
		framework       string
		createRoute     bool
		imagePullSecret string
		authBridge      bool
		noAuthBridge    bool
	)
	c := &cobra.Command{
		Use:   "deploy NAME",
		Short: "Deploy agent from container image (POST /api/v1/agents, deploymentMethod=image)",
		Long: `Creates workload + Service from an existing image. Requires kagenti-operator (or equivalent API role).

Example:
  kubectl kagenti deploy my-agent -n team1 --image quay.io/org/my-agent:v1

Maps to API: deploymentMethod "image", containerImage, workloadType, createHttpRoute, etc.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := validateOutput(rootOutput); err != nil {
				return err
			}
			base, token, err := loadAPI(cmd)
			if err != nil {
				return err
			}
			ns := rootNamespace
			if ns == "" {
				ns, err = kube.CurrentNamespace(cmd.Context())
				if err != nil {
					return err
				}
			}
			name := args[0]
			req := &client.CreateAgentRequest{
				Name:             name,
				Namespace:        ns,
				DeploymentMethod: "image",
				ContainerImage:   image,
				WorkloadType:     workloadType,
				Protocol:         protocol,
				Framework:        framework,
				CreateHTTPRoute:  createRoute,
			}
			if imagePullSecret != "" {
				req.ImagePullSecret = &imagePullSecret
			}
			if noAuthBridge {
				f := false
				req.AuthBridgeEnabled = &f
			} else if cmd.Flags().Changed("auth-bridge") {
				req.AuthBridgeEnabled = &authBridge
			}
			resp, err := client.CreateAgent(cmd.Context(), base, token, req)
			if err != nil {
				return err
			}
			return writeDeployResult(cmd, rootOutput, resp)
		},
	}
	c.Flags().StringVar(&image, "image", "", "Container image (required), e.g. quay.io/ns/img:tag")
	c.Flags().StringVar(&workloadType, "workload-type", "deployment", "deployment | statefulset | job")
	c.Flags().StringVar(&protocol, "protocol", "a2a", "Agent protocol")
	c.Flags().StringVar(&framework, "framework", "LangGraph", "Framework label")
	c.Flags().BoolVar(&createRoute, "create-http-route", false, "Create HTTPRoute/Route for external access")
	c.Flags().StringVar(&imagePullSecret, "image-pull-secret", "", "Kubernetes secret for registry pull")
	c.Flags().BoolVar(&authBridge, "auth-bridge", true, "Inject AuthBridge sidecar (default true)")
	c.Flags().BoolVar(&noAuthBridge, "no-auth-bridge", false, "Disable AuthBridge sidecar")
	_ = c.MarkFlagRequired("image")
	return c
}

func writeDeployResult(cmd *cobra.Command, o string, resp *client.CreateAgentResponse) error {
	w := cmd.OutOrStdout()
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(resp)
	case "yaml":
		b, err := yaml.Marshal(resp)
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	default:
		_, err := fmt.Fprintf(w, "%s\n", resp.Message)
		return err
	}
}
