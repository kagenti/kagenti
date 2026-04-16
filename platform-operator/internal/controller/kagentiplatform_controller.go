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
	"fmt"
	"time"

	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	v1alpha1 "github.com/kagenti/kagenti/platform-operator/api/v1alpha1"
	"github.com/kagenti/kagenti/platform-operator/internal/components"
	"github.com/kagenti/kagenti/platform-operator/internal/infrastructure"
	"github.com/kagenti/kagenti/platform-operator/internal/migration"
)

const (
	finalizerName = "kagenti.dev/platform-cleanup"
	requeueAfter  = 30 * time.Second
)

// KagentiPlatformReconciler reconciles a KagentiPlatform object.
type KagentiPlatformReconciler struct {
	client.Client
	Scheme    *runtime.Scheme
	Registry  *components.Registry
	Validator *infrastructure.Validator
	Fence     *migration.Checker
}

// +kubebuilder:rbac:groups=kagenti.dev,resources=kagentiplatforms,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=kagenti.dev,resources=kagentiplatforms/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=kagenti.dev,resources=kagentiplatforms/finalizers,verbs=update
// +kubebuilder:rbac:groups=apiextensions.k8s.io,resources=customresourcedefinitions,verbs=get;list;watch
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=services;configmaps;secrets;serviceaccounts;namespaces,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=batch,resources=jobs,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=gateway.networking.k8s.io,resources=httproutes;referencegrants,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=rbac.authorization.k8s.io,resources=roles;rolebindings;clusterroles;clusterrolebindings,verbs=get;list;watch;create;update;patch;delete

// Reconcile moves the cluster state toward the desired state declared in KagentiPlatform.
func (r *KagentiPlatformReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	// Fetch the KagentiPlatform instance
	platform := &v1alpha1.KagentiPlatform{}
	if err := r.Get(ctx, req.NamespacedName, platform); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// Handle deletion
	if !platform.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, platform)
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(platform, finalizerName) {
		controllerutil.AddFinalizer(platform, finalizerName)
		if err := r.Update(ctx, platform); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	}

	// Initialize status phase if needed (components/infrastructure populated by reconcile loop)
	if platform.Status.Phase == "" {
		platform.Status.Phase = v1alpha1.PhaseInstalling
		if err := r.Status().Update(ctx, platform); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	}

	// Step 1: Migration fence check
	fenceResult, err := r.Fence.Check(ctx)
	if err != nil {
		log.Error(err, "migration fence check failed")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	if fenceResult.Blocked {
		log.Info("migration fence triggered", "releases", fenceResult.DetectedReleases)
		platform.Status.Phase = v1alpha1.PhaseBlocked
		meta.SetStatusCondition(&platform.Status.Conditions, metav1.Condition{
			Type:               v1alpha1.ConditionMigrationRequired,
			Status:             metav1.ConditionTrue,
			Reason:             v1alpha1.ReasonMigrationRequired,
			Message:            fenceResult.Message,
			ObservedGeneration: platform.Generation,
		})
		if err := r.Status().Update(ctx, platform); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	// Clear migration condition if it was previously set
	meta.RemoveStatusCondition(&platform.Status.Conditions, v1alpha1.ConditionMigrationRequired)

	// Step 2: Validate infrastructure
	infraResults, err := r.Validator.Validate(ctx, &platform.Spec.Infrastructure)
	if err != nil {
		log.Error(err, "infrastructure validation failed")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	platform.Status.Infrastructure = infraResults.ToInfrastructureStatus()

	if !infraResults.AllReady {
		log.Info("required infrastructure missing", "blocked", infraResults.Blocked)
		platform.Status.Phase = v1alpha1.PhaseBlocked
		meta.SetStatusCondition(&platform.Status.Conditions, metav1.Condition{
			Type:               v1alpha1.ConditionInfrastructureReady,
			Status:             metav1.ConditionFalse,
			Reason:             v1alpha1.ReasonInfrastructureMissing,
			Message:            fmt.Sprintf("required infrastructure missing: %v", infraResults.Blocked),
			ObservedGeneration: platform.Generation,
		})
		if err := r.Status().Update(ctx, platform); err != nil {
			return ctrl.Result{}, err
		}
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	meta.SetStatusCondition(&platform.Status.Conditions, metav1.Condition{
		Type:               v1alpha1.ConditionInfrastructureReady,
		Status:             metav1.ConditionTrue,
		Reason:             v1alpha1.ReasonReady,
		Message:            "all required infrastructure dependencies are present",
		ObservedGeneration: platform.Generation,
	})

	// Step 3: Reconcile components
	if platform.Status.Components == nil {
		platform.Status.Components = &v1alpha1.ComponentsStatus{}
	}
	allReady := true
	anyError := false

	for _, comp := range r.Registry.All() {
		compStatus := r.reconcileComponent(ctx, comp, platform)
		r.setComponentStatus(platform, comp.Name(), compStatus)

		if compStatus.Status == v1alpha1.ComponentError {
			anyError = true
			allReady = false
		} else if compStatus.Status == v1alpha1.ComponentInstalling {
			allReady = false
		}
	}

	// Step 4: Update overall phase
	switch {
	case anyError:
		platform.Status.Phase = v1alpha1.PhaseDegraded
	case allReady:
		platform.Status.Phase = v1alpha1.PhaseReady
	default:
		platform.Status.Phase = v1alpha1.PhaseInstalling
	}

	// Update Available condition
	meta.SetStatusCondition(&platform.Status.Conditions, metav1.Condition{
		Type:               v1alpha1.ConditionAvailable,
		Status:             condBool(allReady),
		Reason:             condReason(allReady, v1alpha1.ReasonReady, v1alpha1.ReasonReconciling),
		Message:            condMsg(allReady, "all components ready", "components still reconciling"),
		ObservedGeneration: platform.Generation,
	})

	platform.Status.ObservedGeneration = platform.Generation
	if err := r.Status().Update(ctx, platform); err != nil {
		return ctrl.Result{}, err
	}

	if !allReady {
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	return ctrl.Result{}, nil
}

// reconcileComponent handles a single component's install/uninstall/readiness check.
func (r *KagentiPlatformReconciler) reconcileComponent(
	ctx context.Context,
	comp components.Component,
	platform *v1alpha1.KagentiPlatform,
) v1alpha1.ComponentStatus {
	log := logf.FromContext(ctx).WithValues("component", comp.Name())
	now := metav1.Now()

	if !comp.Enabled(&platform.Spec) {
		log.V(1).Info("component not enabled, ensuring uninstalled")
		if err := comp.Uninstall(ctx); err != nil {
			log.Error(err, "failed to uninstall component")
			return v1alpha1.ComponentStatus{
				Status:             v1alpha1.ComponentError,
				Message:            fmt.Sprintf("uninstall failed: %v", err),
				LastTransitionTime: now,
			}
		}
		return v1alpha1.ComponentStatus{
			Status:             v1alpha1.ComponentRemoved,
			Message:            "component not enabled",
			LastTransitionTime: now,
		}
	}

	// Install or update
	if err := comp.Install(ctx, platform); err != nil {
		log.Error(err, "failed to install component")
		return v1alpha1.ComponentStatus{
			Status:             v1alpha1.ComponentError,
			Message:            fmt.Sprintf("install failed: %v", err),
			LastTransitionTime: now,
		}
	}

	// Check readiness
	ready, msg, err := comp.IsReady(ctx)
	if err != nil {
		log.Error(err, "readiness check failed")
		return v1alpha1.ComponentStatus{
			Status:             v1alpha1.ComponentError,
			Message:            fmt.Sprintf("readiness check error: %v", err),
			LastTransitionTime: now,
		}
	}

	if ready {
		return v1alpha1.ComponentStatus{
			Status:             v1alpha1.ComponentReady,
			Message:            msg,
			LastTransitionTime: now,
		}
	}

	return v1alpha1.ComponentStatus{
		Status:             v1alpha1.ComponentInstalling,
		Message:            msg,
		LastTransitionTime: now,
	}
}

// setComponentStatus updates the status for a named component.
func (r *KagentiPlatformReconciler) setComponentStatus(
	platform *v1alpha1.KagentiPlatform,
	name string,
	status v1alpha1.ComponentStatus,
) {
	if platform.Status.Components == nil {
		platform.Status.Components = &v1alpha1.ComponentsStatus{}
	}

	switch name {
	case "agent-operator":
		platform.Status.Components.AgentOperator = status
	case "webhook":
		platform.Status.Components.Webhook = status
	case "ui":
		platform.Status.Components.UI = status
	case "auth":
		platform.Status.Components.Auth = status
	case "mcp-gateway":
		platform.Status.Components.MCPGateway = status
	}
}

// reconcileDelete handles cleanup when the CR is being deleted.
func (r *KagentiPlatformReconciler) reconcileDelete(
	ctx context.Context,
	platform *v1alpha1.KagentiPlatform,
) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	if platform.Spec.DeletionPolicy == v1alpha1.DeletionPolicyRetain {
		log.Info("deletion policy is Retain, skipping component cleanup")
	} else {
		// Uninstall all components in reverse order
		allComponents := r.Registry.All()
		for i := len(allComponents) - 1; i >= 0; i-- {
			comp := allComponents[i]
			log.Info("uninstalling component", "component", comp.Name())
			if err := comp.Uninstall(ctx); err != nil {
				log.Error(err, "failed to uninstall component", "component", comp.Name())
				return ctrl.Result{RequeueAfter: requeueAfter}, nil
			}
		}
	}

	controllerutil.RemoveFinalizer(platform, finalizerName)
	if err := r.Update(ctx, platform); err != nil {
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *KagentiPlatformReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&v1alpha1.KagentiPlatform{}).
		Named("kagentiplatform").
		Complete(r)
}

func condBool(b bool) metav1.ConditionStatus {
	if b {
		return metav1.ConditionTrue
	}
	return metav1.ConditionFalse
}

func condReason(b bool, ifTrue, ifFalse string) string {
	if b {
		return ifTrue
	}
	return ifFalse
}

func condMsg(b bool, ifTrue, ifFalse string) string {
	if b {
		return ifTrue
	}
	return ifFalse
}
