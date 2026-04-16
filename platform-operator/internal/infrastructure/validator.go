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
	"context"
	"fmt"

	apiextensionsv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
)

var log = logf.Log.WithName("infrastructure-validator")

// infraDep maps an infrastructure component to its well-known CRD names used for detection.
type infraDep struct {
	name     string
	crdNames []string
}

var knownDeps = map[string]infraDep{
	"certManager": {
		name:     "cert-manager",
		crdNames: []string{"certificates.cert-manager.io", "issuers.cert-manager.io"},
	},
	"istio": {
		name:     "Istio",
		crdNames: []string{"virtualservices.networking.istio.io"},
	},
	"spire": {
		name:     "SPIRE",
		crdNames: []string{"clusterspiffeids.spire.spiffe.io"},
	},
	"tekton": {
		name:     "Tekton",
		crdNames: []string{"tasks.tekton.dev", "pipelines.tekton.dev"},
	},
	"shipwright": {
		name:     "Shipwright",
		crdNames: []string{"builds.shipwright.io"},
	},
	"gatewayApi": {
		name:     "Gateway API",
		crdNames: []string{"gateways.gateway.networking.k8s.io", "httproutes.gateway.networking.k8s.io"},
	},
}

// Result holds the validation result for a single infrastructure dependency.
type Result struct {
	Name      string
	Available bool
	Message   string
}

// ValidationResults holds the results of all infrastructure validations.
type ValidationResults struct {
	Results  map[string]Result
	AllReady bool
	Blocked  []string // names of required-but-missing dependencies
}

// Validator checks infrastructure dependencies by looking for their CRDs.
// It uses read-only access — it never creates, updates, or deletes any resources.
type Validator struct {
	client client.Client
}

// NewValidator creates a new infrastructure Validator.
func NewValidator(c client.Client) *Validator {
	return &Validator{client: c}
}

// Validate checks all infrastructure dependencies declared in the spec.
// It returns results for each dependency and whether the overall validation passed.
func (v *Validator) Validate(ctx context.Context, spec *v1alpha1.InfrastructureSpec) (*ValidationResults, error) {
	results := &ValidationResults{
		Results:  make(map[string]Result),
		AllReady: true,
	}

	checks := map[string]v1alpha1.InfraRequirement{
		"certManager": spec.CertManager.Requirement,
		"istio":       spec.Istio.Requirement,
		"spire":       spec.SPIRE.Requirement,
		"tekton":      spec.Tekton.Requirement,
		"shipwright":  spec.Shipwright.Requirement,
		"gatewayApi":  spec.GatewayAPI.Requirement,
	}

	for key, requirement := range checks {
		dep, ok := knownDeps[key]
		if !ok {
			continue
		}

		if requirement == v1alpha1.Ignored {
			results.Results[key] = Result{
				Name:      dep.name,
				Available: false,
				Message:   "ignored by spec",
			}
			continue
		}

		available := v.checkCRDsExist(ctx, dep.crdNames)

		result := Result{
			Name:      dep.name,
			Available: available,
		}

		if available {
			result.Message = "CRDs detected"
		} else {
			result.Message = fmt.Sprintf("%s CRDs not found", dep.name)
		}

		if !available && requirement == v1alpha1.Required {
			results.AllReady = false
			results.Blocked = append(results.Blocked, dep.name)
			result.Message = fmt.Sprintf("%s is required but CRDs are missing", dep.name)
		}

		results.Results[key] = result
	}

	return results, nil
}

// checkCRDsExist checks if at least one of the given CRDs exists in the cluster.
func (v *Validator) checkCRDsExist(ctx context.Context, crdNames []string) bool {
	for _, name := range crdNames {
		crd := &apiextensionsv1.CustomResourceDefinition{}
		err := v.client.Get(ctx, types.NamespacedName{Name: name}, crd)
		if err == nil {
			return true
		}
		log.V(1).Info("CRD not found", "name", name)
	}
	return false
}

// ToInfrastructureStatus converts validation results to CRD status fields.
func (r *ValidationResults) ToInfrastructureStatus() *v1alpha1.InfrastructureStatus {
	status := &v1alpha1.InfrastructureStatus{}

	if res, ok := r.Results["certManager"]; ok {
		status.CertManager = v1alpha1.InfraComponentStatus{
			Available: res.Available,
			Message:   res.Message,
		}
	}
	if res, ok := r.Results["istio"]; ok {
		status.Istio = v1alpha1.InfraComponentStatus{
			Available: res.Available,
			Message:   res.Message,
		}
	}
	if res, ok := r.Results["spire"]; ok {
		status.SPIRE = v1alpha1.InfraComponentStatus{
			Available: res.Available,
			Message:   res.Message,
		}
	}
	if res, ok := r.Results["tekton"]; ok {
		status.Tekton = v1alpha1.InfraComponentStatus{
			Available: res.Available,
			Message:   res.Message,
		}
	}
	if res, ok := r.Results["shipwright"]; ok {
		status.Shipwright = v1alpha1.InfraComponentStatus{
			Available: res.Available,
			Message:   res.Message,
		}
	}
	if res, ok := r.Results["gatewayApi"]; ok {
		status.GatewayAPI = v1alpha1.InfraComponentStatus{
			Available: res.Available,
			Message:   res.Message,
		}
	}

	return status
}
