# Developer's Guide

## Working with Git

### Setting up your local repo

1. Create a [fork of kagenti](https://github.com/kagenti/kagenti/fork)

2. Clone your fork – command only shown for HTTPS; adjust the URL if you prefer SSH

```shell
git clone https://github.com/<your-username>/kagenti.git
cd kagenti
```

3. Add the upstream repository as a remote (adjust the URL if you prefer SSH)

```shell
git remote add upstream https://github.com/kagenti/kagenti.git
```

4. Fetch all tags from upstream

```shell
git fetch upstream --tags
```

### Pre-commit

This project leverages [pre-commit](https://pre-commit.com/) to enforce consistency in code style and run checks prior to commits with linters and formatters.

Installation can be done via [directions here](https://pre-commit.com/#installation) or `brew install pre-commit` on MacOS.

From the project base, this will install the Git hook:
```sh
pre-commit install
```

To run against all files manually:
```sh
pre-commit run --all-files
```

VSCode extensions such as this [pre-commit-helper](https://marketplace.visualstudio.com/items?itemName=elagil.pre-commit-helper) can be configured to run directly when files are saved in VSCode.

### Making a PR

Work on your local repo cloned from your fork. Create a branch:

```shell
git checkout -b <name-of-your-branch>
```

When ready to make your PR, make sure first to rebase from upstream
(things may have changed while you have been working on the PR):

```shell
git checkout main; git fetch upstream; git merge --ff-only upstream/main
git checkout <name-of-your-branch>
git rebase main
```

Resolve any conflict if needed, then you can make your PR by doing:

```shell
git commit -am "<your commit message>" -s
```

Note that commits must be all signed off to pass DCO checks.
It is reccomended (but not enforced) to follow best practices
for commits comments such as [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/).

Push the PR:

```shell
 git push --set-upstream origin <name-of-your-branch>
 ```

 Open the URL printed by the git push command for the PR and complete the PR by
 entering all the required info - pay attention to the type of PR indicator that goes
 at the start of the title, a meaningful description of what the PR does
 and possibly which issue is neing fixed.


### Tagging and triggering a build for new tag

Note - this is only enabled for maintainers for the project.

Checkout `main` and make sure it equals `main` in the upstream repo as follows:

if working on a fork and "upstream" is the name of the upstream remote (commmon convention)

```shell
git checkout main; git fetch upstream; git merge --ff-only upstream/main
```

if a maintainer using a branch upstream directly (not reccomended)

```shell
git checkout main; git pull
```

check existing tags e.g.,

```shell
git tag
v0.0.1-alpha.1
v0.0.2-alpha.1
...
v0.0.4-alpha.9
```

create a new tag e.g.

```shell
git tag v0.0.4-alpha.10
```

Push the tag upstream

```shell
git push upstream v0.0.4-alpha.10
```

## Kagenti UI Development

### Running locally

To run the UI locally, ensure you have Python version 3.12 or above installed.
If Kagenti is not already running, execute the installer to set up Kagenti first.
Follow these steps to run the UI:

1. Navigate to the kagenti/ui directory:

    ```shell
    cd kagenti/ui
    ```

2. Launch the UI using the following Streamlit command:

    ```shell
    uv run streamlit run Home.py
    ```

Access the UI in your browser at `http://localhost:8501`.

Note: Running locally allows you to explore various UI features except for connecting to an agent or tool, which requires exposing them via an HTTPRoute.

Example: Connecting to `a2a-currency-converter`

To test connectivity with the `a2a-currency-converter` agent within
the team1 namespace, apply the following HTTPRoute configuration:

```shell
kubectl apply -n team1 -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: a2a-currency-converter
  labels:
    app: a2a-currency-converter
spec:
  parentRefs:
    - name: http
      namespace: kagenti-system
  hostnames:
    - "a2a-currency-converter.localtest.me"
  rules:
    - backendRefs:
        - name: a2a-currency-converter
          port: 8000
EOF
```

### Running Your Image in Kubernetes

Before proceeding, ensure there is an existing Kagenti instance
running. To test your build on Kubernetes, execute the following script:

```shell
scripts/ui-dev-build.sh
```

Script Details:

- Builds the image locally.
- The image is loaded into Kind.
- The script replaces the image in the kagenti-ui pod with the newly built image.

Once complete, access the UI at http://kagenti-ui.localtest.me:8080.

