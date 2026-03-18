// Copyright 2025 IBM Corp.
// SPDX-License-Identifier: Apache-2.0

package cli

import (
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"github.com/kagenti/kagenti/kagenti/kubectl-kagenti/internal/client"
	"gopkg.in/yaml.v3"
)

func validateOutput(o string) error {
	if o == "" {
		return nil
	}
	switch o {
	case "json", "yaml", "wide":
		return nil
	default:
		return fmt.Errorf("invalid -o/--output %q (use json, yaml, or wide)", o)
	}
}

func writeUserInfo(w io.Writer, o string, u *client.UserInfo) error {
	switch o {
	case "json":
		enc := json.NewEncoder(w)
		enc.SetIndent("", "  ")
		return enc.Encode(u)
	case "yaml":
		b, err := yaml.Marshal(u)
		if err != nil {
			return err
		}
		_, err = w.Write(b)
		return err
	case "wide":
		email := ""
		if u.Email != nil {
			email = *u.Email
		}
		_, err := fmt.Fprintf(w, "USERNAME\tEMAIL\tROLES\tAUTHENTICATED\n%s\t%s\t%s\t%v\n",
			u.Username, email, strings.Join(u.Roles, ","), u.Authenticated)
		return err
	default:
		_, err := fmt.Fprintf(w, "User: %s  authenticated=%v  roles=[%s]\n",
			u.Username, u.Authenticated, strings.Join(u.Roles, ", "))
		return err
	}
}
