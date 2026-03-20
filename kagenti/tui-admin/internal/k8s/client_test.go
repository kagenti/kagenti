package k8s

import (
	"context"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func newFakeClient(objects ...metav1.Object) *Client {
	var runtimeObjects []metav1.Object
	runtimeObjects = append(runtimeObjects, objects...)
	// Convert to runtime.Object for fake client
	fakeClientset := fake.NewSimpleClientset()
	return &Client{Clientset: fakeClientset}
}

func TestCreateNamespace(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset()}

	err := c.CreateNamespace(context.Background(), "test-ns")
	if err != nil {
		t.Fatalf("CreateNamespace failed: %v", err)
	}

	// Verify it exists
	ns, err := c.Clientset.CoreV1().Namespaces().Get(context.Background(), "test-ns", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("namespace not created: %v", err)
	}
	if ns.Name != "test-ns" {
		t.Errorf("name: got %q, want test-ns", ns.Name)
	}
}

func TestCreateNamespaceIdempotent(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset(
		&corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "existing"}},
	)}

	// Should not error when namespace already exists
	err := c.CreateNamespace(context.Background(), "existing")
	if err != nil {
		t.Fatalf("CreateNamespace should be idempotent: %v", err)
	}
}

func TestCreateSecret(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset(
		&corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "team1"}},
	)}

	data := map[string][]byte{
		"api-key": []byte("test-key-123"),
	}
	err := c.CreateSecret(context.Background(), "team1", "llm-secret", data)
	if err != nil {
		t.Fatalf("CreateSecret failed: %v", err)
	}

	// Verify
	secret, err := c.Clientset.CoreV1().Secrets("team1").Get(context.Background(), "llm-secret", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("secret not found: %v", err)
	}
	if string(secret.Data["api-key"]) != "test-key-123" {
		t.Errorf("api-key: got %q, want test-key-123", string(secret.Data["api-key"]))
	}
}

func TestCreateSecretUpdate(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset(
		&corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "team1"}},
		&corev1.Secret{
			ObjectMeta: metav1.ObjectMeta{Name: "existing-secret", Namespace: "team1"},
			Data:       map[string][]byte{"old-key": []byte("old-value")},
		},
	)}

	// Update existing secret
	newData := map[string][]byte{"new-key": []byte("new-value")}
	err := c.CreateSecret(context.Background(), "team1", "existing-secret", newData)
	if err != nil {
		t.Fatalf("CreateSecret update failed: %v", err)
	}

	secret, _ := c.Clientset.CoreV1().Secrets("team1").Get(context.Background(), "existing-secret", metav1.GetOptions{})
	if string(secret.Data["new-key"]) != "new-value" {
		t.Error("secret should have updated data")
	}
	if _, ok := secret.Data["old-key"]; ok {
		t.Error("old key should be gone after update")
	}
}

func TestWaitForDeployment(t *testing.T) {
	t.Parallel()
	replicas := int32(1)
	c := &Client{Clientset: fake.NewSimpleClientset(
		&appsv1.Deployment{
			ObjectMeta: metav1.ObjectMeta{Name: "kagenti-backend", Namespace: "kagenti-system"},
			Spec:       appsv1.DeploymentSpec{Replicas: &replicas},
			Status:     appsv1.DeploymentStatus{AvailableReplicas: 1},
		},
	)}

	err := c.WaitForDeployment(context.Background(), "kagenti-system", "kagenti-backend", 5*time.Second)
	if err != nil {
		t.Fatalf("WaitForDeployment failed: %v", err)
	}
}

func TestWaitForDeploymentTimeout(t *testing.T) {
	t.Parallel()
	replicas := int32(3)
	c := &Client{Clientset: fake.NewSimpleClientset(
		&appsv1.Deployment{
			ObjectMeta: metav1.ObjectMeta{Name: "not-ready", Namespace: "ns"},
			Spec:       appsv1.DeploymentSpec{Replicas: &replicas},
			Status:     appsv1.DeploymentStatus{AvailableReplicas: 0}, // not ready
		},
	)}

	err := c.WaitForDeployment(context.Background(), "ns", "not-ready", 1*time.Second)
	if err == nil {
		t.Error("expected timeout error")
	}
}

func TestWaitForNamespace(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset(
		&corev1.Pod{
			ObjectMeta: metav1.ObjectMeta{Name: "pod1", Namespace: "kagenti-system"},
			Status:     corev1.PodStatus{Phase: corev1.PodRunning},
		},
	)}

	err := c.WaitForNamespace(context.Background(), "kagenti-system", 5*time.Second)
	if err != nil {
		t.Fatalf("WaitForNamespace failed: %v", err)
	}
}

func TestWaitForNamespaceEmpty(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset()}

	// Empty namespace should timeout (no pods)
	err := c.WaitForNamespace(context.Background(), "empty-ns", 1*time.Second)
	if err == nil {
		t.Error("expected timeout for empty namespace")
	}
}

func TestGetNodes(t *testing.T) {
	t.Parallel()
	c := &Client{Clientset: fake.NewSimpleClientset(
		&corev1.Node{
			ObjectMeta: metav1.ObjectMeta{Name: "node1"},
			Status: corev1.NodeStatus{
				Addresses: []corev1.NodeAddress{
					{Type: corev1.NodeInternalIP, Address: "192.168.1.1"},
				},
			},
		},
		&corev1.Node{
			ObjectMeta: metav1.ObjectMeta{Name: "node2"},
		},
	)}

	nodes, err := c.GetNodes(context.Background())
	if err != nil {
		t.Fatalf("GetNodes failed: %v", err)
	}
	if len(nodes) != 2 {
		t.Errorf("expected 2 nodes, got %d", len(nodes))
	}
	if nodes[0].Name != "node1" {
		t.Errorf("first node: got %q, want node1", nodes[0].Name)
	}
}
