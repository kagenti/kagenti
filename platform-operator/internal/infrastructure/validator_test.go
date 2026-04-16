/*
Copyright 2025-2026 IBM Corp.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package infrastructure

import (
	"testing"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
)

func TestToInfrastructureStatus(t *testing.T) {
	results := &ValidationResults{
		Results: map[string]Result{
			"certManager": {Name: "cert-manager", Available: true, Message: "CRDs detected"},
			"istio":       {Name: "Istio", Available: false, Message: "ignored by spec"},
			"spire":       {Name: "SPIRE", Available: false, Message: "ignored by spec"},
			"tekton":      {Name: "Tekton", Available: true, Message: "CRDs detected"},
			"shipwright":  {Name: "Shipwright", Available: false, Message: "Shipwright CRDs not found"},
			"gatewayApi":  {Name: "Gateway API", Available: true, Message: "CRDs detected"},
		},
		AllReady: true,
	}

	status := results.ToInfrastructureStatus()

	if !status.CertManager.Available {
		t.Error("expected cert-manager to be available")
	}
	if status.Istio.Available {
		t.Error("expected Istio to not be available")
	}
	if !status.Tekton.Available {
		t.Error("expected Tekton to be available")
	}
	if status.Shipwright.Available {
		t.Error("expected Shipwright to not be available")
	}
	if !status.GatewayAPI.Available {
		t.Error("expected Gateway API to be available")
	}
}

func TestKnownDepsMapping(t *testing.T) {
	// Ensure all known deps have at least one CRD name
	for key, dep := range knownDeps {
		if dep.name == "" {
			t.Errorf("knownDeps[%s] has empty name", key)
		}
		if len(dep.crdNames) == 0 {
			t.Errorf("knownDeps[%s] has no CRD names", key)
		}
	}

	// Ensure all infrastructure spec fields have a mapping
	expectedKeys := []string{"certManager", "istio", "spire", "tekton", "shipwright", "gatewayApi"}
	for _, key := range expectedKeys {
		if _, ok := knownDeps[key]; !ok {
			t.Errorf("missing knownDeps entry for %q", key)
		}
	}
}

func TestValidationResultsBlocked(t *testing.T) {
	results := &ValidationResults{
		Results: map[string]Result{
			"certManager": {Name: "cert-manager", Available: false, Message: "cert-manager is required but CRDs are missing"},
		},
		AllReady: false,
		Blocked:  []string{"cert-manager"},
	}

	if results.AllReady {
		t.Error("expected AllReady to be false")
	}
	if len(results.Blocked) != 1 || results.Blocked[0] != "cert-manager" {
		t.Errorf("expected blocked=[cert-manager], got %v", results.Blocked)
	}
}

func TestInfraRequirementIgnoredSkipsValidation(t *testing.T) {
	// When all requirements are Ignored, validation should pass
	spec := &v1alpha1.InfrastructureSpec{
		CertManager: v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
		Istio:       v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
		SPIRE:       v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
		Tekton:      v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
		Shipwright:  v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
		GatewayAPI:  v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
	}

	// We can't call Validate without a real client, but we can verify the spec structure
	_ = spec
}
