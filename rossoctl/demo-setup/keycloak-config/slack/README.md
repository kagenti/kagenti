# Keycloak Configuration for Authorized Slack Research Agent Demo

This script configures Keycloak for the [Authorized Slack Research Agent Demo](../../../../docs/demo-slack-research-agent.md), where logging into Rossoctl with accounts of different permissions affects the results those accounts recieve.

This script performs the following steps:
1) Create the `slack-partial-access` client scope
2) Assign the `slack-partial-access` realm role to the `slack-partial-access` client scope
3) Set the `slack-partial-access` client scope as the default client scope
4) Create the `slack-full-access` client scope
5) Assign the `slack-full-access` realm role to the `slack-full-access` client scope
6) Set the `slack-full-access` client scope as the default client scope
7) Add the `slack-partial-access` and `slack-full-access` client scopes to the `rossoctl` client
8) Create the `slack-partial-access-user` user with a password "password"
9) Assign the `slack-partial-access` realm role to `slack-partial-access-user`
10) Create the `slack-full-access-user` user with a password "password"
11) Assign the `slack-partial-access` and `slack-full-access` realm roles to `slack-full-access-user`
12) Enable service accounts for the `spiffe://localtest.me/ns/{NAMESPACE}/sa/slack-tool` client
13) Assign `view-clients` (master realm) client role to `spiffe://localtest.me/ns/{NAMESPACE}/sa/slack-tool` client
14) Set the realm access token lifespan to 10 minutes

The script assumes there to be:
* `rossoctl` client
* `spiffe://localtest.me/ns/{NAMESPACE}/sa/slack-tool` client
* `view-clients` client role in the realm
* `slack-partial-access` realm role
* `slack-full-access` realm role

These components should be installed by the Rossoctl installer (`scripts/kind/setup-rossoctl.sh`).

### Instructions

Run the installer:

```sh
# From repository root
scripts/kind/setup-rossoctl.sh
```

Set up Python environment

```sh
cd rossoctl/demo-setup/keycloak-config/slack
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

python set_up_slack_demo.py
```
