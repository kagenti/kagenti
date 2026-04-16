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

package migration

import (
	"context"
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
)

var log = logf.Log.WithName("migration-fence")

const (
	// helmManagedByLabel is the standard Helm label for managed-by tracking.
	helmManagedByLabel = "app.kubernetes.io/managed-by"

	// helmManagedByValue is the default value Helm sets.
	helmManagedByValue = "Helm"

	// operatorManagedByValue is the value set after adoption.
	operatorManagedByValue = "kagenti-platform-operator"

	// helmReleaseTypeLabel identifies Helm release secrets.
	helmReleaseTypeLabel = "owner"
	helmReleaseTypeValue = "helm"

	// targetNamespace is the namespace where Kagenti Helm releases live.
	targetNamespace = "kagenti-system"
)

// releaseNames are the Helm release names we look for when checking for existing installs.
var releaseNames = []string{"kagenti", "kagenti-deps"}

// FenceResult describes the outcome of a migration fence check.
type FenceResult struct {
	// Blocked is true if an existing unmanaged Helm install was detected.
	Blocked bool

	// Message provides human-readable detail.
	Message string

	// DetectedReleases lists the Helm release names found.
	DetectedReleases []string
}

// Checker detects existing Ansible/Helm-managed Kagenti installations.
type Checker struct {
	client client.Client
}

// NewChecker creates a new migration fence Checker.
func NewChecker(c client.Client) *Checker {
	return &Checker{client: c}
}

// Check looks for Helm release Secrets in kagenti-system that are not owned by the platform operator.
// Helm stores release state as Secrets with label "owner=helm" and name "sh.helm.release.v1.<name>.v<N>".
func (c *Checker) Check(ctx context.Context) (*FenceResult, error) {
	// List all Secrets in kagenti-system with the Helm owner label
	secrets := &corev1.SecretList{}
	err := c.client.List(ctx, secrets,
		client.InNamespace(targetNamespace),
		client.MatchingLabels{helmReleaseTypeLabel: helmReleaseTypeValue},
	)
	if err != nil {
		return nil, fmt.Errorf("failed to list Helm release secrets: %w", err)
	}

	var unownedReleases []string
	seen := make(map[string]bool)

	for _, secret := range secrets.Items {
		// Extract release name from secret name: sh.helm.release.v1.<name>.v<N>
		releaseName := extractReleaseName(secret.Name)
		if releaseName == "" {
			continue
		}

		// Check if this is one of the Kagenti releases
		isKagentiRelease := false
		for _, name := range releaseNames {
			if releaseName == name {
				isKagentiRelease = true
				break
			}
		}
		if !isKagentiRelease {
			continue
		}

		// Check if already adopted by the platform operator
		managedBy := secret.Labels[helmManagedByLabel]
		if managedBy == operatorManagedByValue {
			log.V(1).Info("Helm release already adopted", "release", releaseName)
			continue
		}

		if !seen[releaseName] {
			seen[releaseName] = true
			unownedReleases = append(unownedReleases, releaseName)
		}
	}

	if len(unownedReleases) > 0 {
		return &FenceResult{
			Blocked:          true,
			Message:          fmt.Sprintf("existing Helm releases found managed by Ansible/manual install: %v. Run 'make adopt' or delete releases before the operator can manage the platform", unownedReleases),
			DetectedReleases: unownedReleases,
		}, nil
	}

	return &FenceResult{
		Blocked: false,
		Message: "no conflicting Helm releases detected",
	}, nil
}

// extractReleaseName extracts the release name from a Helm release secret name.
// Helm release secrets follow the pattern: sh.helm.release.v1.<name>.v<revision>
func extractReleaseName(secretName string) string {
	const prefix = "sh.helm.release.v1."
	if !strings.HasPrefix(secretName, prefix) {
		return ""
	}

	rest := secretName[len(prefix):]
	// Find the last dot followed by v<digits>
	lastDot := strings.LastIndex(rest, ".")
	if lastDot <= 0 {
		return ""
	}

	return rest[:lastDot]
}
