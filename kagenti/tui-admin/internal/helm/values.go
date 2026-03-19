package helm

import (
	"fmt"
	"os"
	"path/filepath"

	"sigs.k8s.io/yaml"
)

// LoadValuesFile reads a YAML values file and returns it as a map.
func LoadValuesFile(path string) (map[string]interface{}, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read values file %s: %w", path, err)
	}

	var values map[string]interface{}
	if err := yaml.Unmarshal(data, &values); err != nil {
		return nil, fmt.Errorf("parse values file %s: %w", path, err)
	}

	return values, nil
}

// MergeValues merges multiple value maps. Later maps override earlier ones.
func MergeValues(base map[string]interface{}, overlays ...map[string]interface{}) map[string]interface{} {
	result := make(map[string]interface{})
	for k, v := range base {
		result[k] = v
	}
	for _, overlay := range overlays {
		for k, v := range overlay {
			if baseMap, ok := result[k].(map[string]interface{}); ok {
				if overlayMap, ok := v.(map[string]interface{}); ok {
					result[k] = MergeValues(baseMap, overlayMap)
					continue
				}
			}
			result[k] = v
		}
	}
	return result
}

// ResolveEnvValues loads the values file for a given environment name.
func ResolveEnvValues(repoRoot, env string) (map[string]interface{}, error) {
	envFiles := map[string]string{
		"dev": "dev_values.yaml",
		"k3s": "k3s_values.yaml",
		"ocp": "ocp_values.yaml",
	}

	fileName, ok := envFiles[env]
	if !ok {
		return nil, fmt.Errorf("unknown environment: %s (valid: dev, k3s, ocp)", env)
	}

	path := filepath.Join(repoRoot, "deployments", "envs", fileName)
	return LoadValuesFile(path)
}

// ResolveSecretValues loads the secret values file.
func ResolveSecretValues(repoRoot string) (map[string]interface{}, error) {
	path := filepath.Join(repoRoot, "deployments", "envs", ".secret_values.yaml")
	if _, err := os.Stat(path); os.IsNotExist(err) {
		return nil, nil // No secrets file is OK
	}
	return LoadValuesFile(path)
}
