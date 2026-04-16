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
	"testing"
)

func TestExtractReleaseName(t *testing.T) {
	tests := []struct {
		secretName string
		want       string
	}{
		{
			secretName: "sh.helm.release.v1.kagenti.v1",
			want:       "kagenti",
		},
		{
			secretName: "sh.helm.release.v1.kagenti.v12",
			want:       "kagenti",
		},
		{
			secretName: "sh.helm.release.v1.kagenti-deps.v1",
			want:       "kagenti-deps",
		},
		{
			secretName: "sh.helm.release.v1.kagenti-deps.v3",
			want:       "kagenti-deps",
		},
		{
			secretName: "some-other-secret",
			want:       "",
		},
		{
			secretName: "sh.helm.release.v1.",
			want:       "",
		},
		{
			secretName: "",
			want:       "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.secretName, func(t *testing.T) {
			got := extractReleaseName(tt.secretName)
			if got != tt.want {
				t.Errorf("extractReleaseName(%q) = %q, want %q", tt.secretName, got, tt.want)
			}
		})
	}
}
