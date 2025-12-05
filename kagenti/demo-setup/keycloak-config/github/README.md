# Keycloak Configuration for GitHub Issue Demo

This script configures Keycloak for the [GitHub Issue Demo](../../../../docs/demo-github-issue.md), where logging into Kagenti with accounts of different permissions affects the results those accounts recieve.

This script performs the following steps:

1. Create the `github-partial-access` client scope  
2. Assign the `github-partial-access` realm role to the `github-partial-access` client scope  
3. Add an audience protocol mapper for `spiffe://localtest.me/ns/<namespace>/sa/github-tool` to the `github-partial-access` client scope  
4. Set the `github-partial-access` client scope as a default client scope  
5. Create the `github-full-access` client scope  
6. Assign the `github-full-access` realm role to the `github-full-access` client scope  
7. Set the `github-full-access` client scope as a default client scope  
8. Create the `github-agent-access` client scope  
9. Assign the `github-agent-access` realm role to the `github-agent-access` client scope  
10. Add an audience protocol mapper for `spiffe://localtest.me/ns/<namespace>/sa/git-issue-agent` to the `github-agent-access` client scope  
11. Set the `github-agent-access` client scope as a default client scope  
12. Add the `github-partial-access`, `github-full-access`, and `github-agent-access` client scopes to the `kagenti` client  
13. Add the `github-partial-access` and `github-full-access` client scopes as optional scopes to the `git-issue-agent` client  
14. Create the `github-partial-access-user` user with password `"password"`  
15. Assign the `github-partial-access` and `github-agent-access` realm roles to `github-partial-access-user`  
16. Create the `github-full-access-user` user with password `"password"`  
17. Assign the `github-partial-access`, `github-full-access`, and `github-agent-access` realm roles to `github-full-access-user`  
18. Set the realm access token lifespan to 10 minutes  

The script assumes the existence of:  
* `kagenti` client  
* `spiffe://localtest.me/ns/<namespace>/sa/github-tool` client  
* `spiffe://localtest.me/ns/<namespace>/sa/git-issue-agent` client  
* `github-partial-access`, `github-full-access`, and `github-agent-access` realm roles  


### Instructions

Run the Kagenti installer

```sh
cd kagenti/installer
uv run kagenti-installer
```

Set up Python environment

```sh
cd kagenti/demo-setup/keycloak-config/github
python -m venv venv
```

Install Python modules

```sh
pip install -r requirements.txt
```

Run Python script

```sh
export KEYCLOAK_URL="http://keycloak.localtest.me:8080"
export KEYCLOAK_REALM=master
export KEYCLOAK_ADMIN_USERNAME=admin
export KEYCLOAK_ADMIN_PASSWORD=admin
export NAMESPACE=<namespace>

python set_up_github_issue_demo.py
```
