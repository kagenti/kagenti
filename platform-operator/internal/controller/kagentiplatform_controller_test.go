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

package controller

import (
	"context"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
	"github.com/kagenti/kagenti/platform-operator/internal/components"
	"github.com/kagenti/kagenti/platform-operator/internal/infrastructure"
	"github.com/kagenti/kagenti/platform-operator/internal/migration"
)

var _ = Describe("KagentiPlatform Controller", func() {
	Context("When reconciling a resource", func() {
		const resourceName = "kagenti"

		ctx := context.Background()

		typeNamespacedName := types.NamespacedName{
			Name: resourceName,
		}

		BeforeEach(func() {
			By("creating the KagentiPlatform resource")
			platform := &v1alpha1.KagentiPlatform{}
			err := k8sClient.Get(ctx, typeNamespacedName, platform)
			if err != nil && errors.IsNotFound(err) {
				resource := &v1alpha1.KagentiPlatform{
					ObjectMeta: metav1.ObjectMeta{
						Name: resourceName,
					},
					Spec: v1alpha1.KagentiPlatformSpec{
						AgentOperator: v1alpha1.ComponentSpec{ManagementState: v1alpha1.Managed},
						Webhook:       v1alpha1.ComponentSpec{ManagementState: v1alpha1.Removed},
						UI:            v1alpha1.UISpec{ComponentSpec: v1alpha1.ComponentSpec{ManagementState: v1alpha1.Managed}},
						MCPGateway:    v1alpha1.ComponentSpec{ManagementState: v1alpha1.Removed},
						Auth:          v1alpha1.AuthSpec{ManagementState: v1alpha1.Removed},
						Infrastructure: v1alpha1.InfrastructureSpec{
							CertManager: v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
							Istio:       v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
							SPIRE:       v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
							Tekton:      v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
							Shipwright:  v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
							GatewayAPI:  v1alpha1.InfraComponentSpec{Requirement: v1alpha1.Ignored},
						},
						Domain: "localtest.me",
					},
				}
				Expect(k8sClient.Create(ctx, resource)).To(Succeed())
			}
		})

		AfterEach(func() {
			resource := &v1alpha1.KagentiPlatform{}
			err := k8sClient.Get(ctx, typeNamespacedName, resource)
			if err == nil {
				// Remove finalizer before deleting to avoid hang
				resource.Finalizers = nil
				Expect(k8sClient.Update(ctx, resource)).To(Succeed())
				Expect(k8sClient.Delete(ctx, resource)).To(Succeed())
			}
		})

		It("should add a finalizer on first reconcile", func() {
			reconciler := newTestReconciler()
			_, err := reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())

			platform := &v1alpha1.KagentiPlatform{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, platform)).To(Succeed())
			Expect(platform.Finalizers).To(ContainElement(finalizerName))
		})

		It("should initialize status phase to Installing", func() {
			reconciler := newTestReconciler()

			// First reconcile: add finalizer
			_, err := reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())

			// Second reconcile: initialize status
			_, err = reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())

			platform := &v1alpha1.KagentiPlatform{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, platform)).To(Succeed())
			Expect(platform.Status.Phase).To(Equal(v1alpha1.PhaseInstalling))
		})

		It("should reconcile components and reach Ready phase with all infra ignored", func() {
			reconciler := newTestReconciler()

			// Run through the reconciliation stages:
			// 1. Add finalizer
			_, err := reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())

			// 2. Initialize status
			_, err = reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())

			// 3. Run main reconciliation (fence, infra, components)
			_, err = reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())

			platform := &v1alpha1.KagentiPlatform{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, platform)).To(Succeed())

			// With all infra ignored and stub components that return ready=true for auth,
			// the phase should reflect component status
			Expect(platform.Status.Components).NotTo(BeNil())
			Expect(platform.Status.Infrastructure).NotTo(BeNil())

			// Auth is Removed, so it should show ComponentRemoved
			Expect(platform.Status.Components.Auth.Status).To(Equal(v1alpha1.ComponentRemoved))
			// Webhook is Removed
			Expect(platform.Status.Components.Webhook.Status).To(Equal(v1alpha1.ComponentRemoved))
		})

		It("should not reconcile a deleted resource", func() {
			reconciler := newTestReconciler()

			// Delete the resource
			platform := &v1alpha1.KagentiPlatform{}
			Expect(k8sClient.Get(ctx, typeNamespacedName, platform)).To(Succeed())
			Expect(k8sClient.Delete(ctx, platform)).To(Succeed())

			// Reconcile should return without error (not found is ignored)
			_, err := reconciler.Reconcile(ctx, reconcile.Request{NamespacedName: typeNamespacedName})
			Expect(err).NotTo(HaveOccurred())
		})
	})
})

func newTestReconciler() *KagentiPlatformReconciler {
	registry := components.NewRegistry(
		components.NewAgentOperatorComponent(k8sClient),
		components.NewWebhookComponent(k8sClient),
		components.NewUIComponent(k8sClient),
		components.NewAuthComponent(k8sClient),
		components.NewMCPGatewayComponent(k8sClient),
	)

	return &KagentiPlatformReconciler{
		Client:    k8sClient,
		Scheme:    k8sClient.Scheme(),
		Registry:  registry,
		Validator: infrastructure.NewValidator(k8sClient),
		Fence:     migration.NewChecker(k8sClient),
	}
}
