// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package authoidc

import "testing"

func TestFromConsoleURL(t *testing.T) {
	ep, err := fromConsoleURL("https://keycloak.example.com/admin/kagenti/console/", "")
	if err != nil {
		t.Fatal(err)
	}
	if ep.ClientID != "kagenti-ui" {
		t.Errorf("client id %q", ep.ClientID)
	}
	if ep.AuthURL != "https://keycloak.example.com/realms/kagenti/protocol/openid-connect/auth" {
		t.Errorf("auth %q", ep.AuthURL)
	}
}
