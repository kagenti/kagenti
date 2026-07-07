---
sidebar_label: Build & Deploy an Agent
sidebar_position: 1
---

# Build and Deploy an Agent

This guide covers the full path from source to a running, governed agent — including in-cluster builds, configuration, and promotion between namespaces. If you just want the two-minute version, see [Deploy your first agent](../getting-started/deploy-your-first-agent.md).

## Build from source, in-cluster

Rosso can build your agent image inside the cluster with [Shipwright](https://shipwright.io/), so contributors don't need a local Docker setup or registry credentials:

```bash
rossoctl agent deploy orders-agent \
  --source https://github.com/my-org/orders-agent \
  --revision main \
  --namespace team1
```

The operator runs the build, pushes to the in-cluster registry, and rolls out the workload.

<details>
<summary>Advanced: choose a build strategy</summary>

Rosso supports multiple build strategies (for example `buildah` and `buildah-insecure-push` for local
registries). Set the strategy when your registry or base image needs it:

```bash
rossoctl agent deploy orders-agent \
  --source https://github.com/my-org/orders-agent \
  --build-strategy buildah \
  --namespace team1
```

</details>

## Configuration and secrets

Pass configuration as environment variables and keep secrets in a `Secret`:

```bash
rossoctl agent deploy orders-agent \
  --source https://github.com/my-org/orders-agent \
  --env-from-file ./orders.env \
  --secret orders-credentials \
  --namespace team1
```

:::warning
Don't bake credentials into images or inline them in the CR. Rosso injects runtime identity and
short-lived tokens; most agents need no long-lived secrets. See [Security & Identity](../security/overview.md).
:::

## Promote across environments

Namespaces are your isolation boundary between teams and stages. Promote a validated agent by deploying the same image to the next namespace:

```bash
rossoctl agent promote orders-agent --from team1 --to staging
```

## Verify

```bash
rossoctl agent describe orders-agent --namespace staging
rossoctl agent chat orders-agent --namespace staging
```

:::note For contributors
Confirm build-strategy names, `--env-from-file`, and any `promote` command against
`kagenti/docs/new-agent.md` and `kagenti/docs/dev-guide.md`. Add a real sample repo link.
:::
