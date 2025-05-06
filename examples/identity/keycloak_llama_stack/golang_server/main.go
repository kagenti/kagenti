// Assisted by watsonx Code Assistant
package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"strings"

	oidc "github.com/coreos/go-oidc"
)

func helloWorld(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintf(w, "Hello, world!")
}

func validateAgainstAuthServer(issuer string, clientid string, bearer string) error {
	// OIDC Discovery
	provider, err := oidc.NewProvider(context.Background(), issuer)
	if err != nil {
		return fmt.Errorf("Failed to discover provider: %w", err)
	}

	// get the verifier
	verifierConfig := oidc.Config{
		ClientID: clientid, // expected audience
	}
	verifier := provider.Verifier(&verifierConfig)
	token, err := verifier.Verify(context.Background(), bearer)
	if err != nil {
		fmt.Printf("Token validation failed %v\n", err)
		return fmt.Errorf("Token validation failed: %w", err)
	}

	// decode token
	// struct to parse claim for client role
	var claims struct {
		RealmRoles struct {
			Roles []string `json:"roles"`
		} `json:"realm_access"`
	}

	if err := token.Claims(&claims); err != nil {
		fmt.Printf("Token decoding failed %v\n", err)
		return fmt.Errorf("Failed to decode token claims")
	}

	// print claims
	fmt.Printf("Received access token with Subject %s and Roles %v\n", token.Subject, claims.RealmRoles.Roles)

	return nil
}

func bearerTokenMiddleware(next http.Handler, issuer string, clientid string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			http.Error(w, "Missing Authorization header", http.StatusUnauthorized)
			return
		}

		tokenString := strings.Split(authHeader, " ")[1]
		fmt.Printf("Validating token %s against issuer %s\n", tokenString, issuer)

		err := validateAgainstAuthServer(issuer, clientid, tokenString)
		if err != nil {
			http.Error(w, fmt.Sprintf("Unauthorized token: %v", err), http.StatusUnauthorized)
			return
		}

		next.ServeHTTP(w, r)
	})
}

func main() {
	// basic arguments
	port := flag.String("port", "10000", "Port to listen on")
	issuer := flag.String("issuer", "https://your-issuer-server.com", "Issuer server URL")
	clientid := flag.String("clientid", "my-external-tool", "Expected audience of incoming access tokens")
	flag.Parse()

	basicFunction := http.HandlerFunc(helloWorld)
	bearerTokenHandler := bearerTokenMiddleware(basicFunction, *issuer, *clientid)
	http.Handle("/", bearerTokenHandler)
	http.ListenAndServe(fmt.Sprintf(":%s", *port), nil)
}
