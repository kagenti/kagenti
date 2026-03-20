# Custom Configs

Place your custom agent variant configs here. Files in this directory are
gitignored (user-specific) except for this README and the templates in
`../examples/`.

## Usage

```bash
# Deploy with a custom agent config
kagenti-admin deploy agent --config configs/custom/my-sandbox-agent.yaml

# Use a config during cluster creation
kagenti-admin cluster create --platform kind --agents configs/custom/my-agents.yaml

# Override existing agent config (requires --force)
kagenti-admin deploy agent --config configs/custom/new-config.yaml --force
```

## Config Format

```yaml
# my-sandbox-agent.yaml
agents:
  - name: sandbox-legion
    namespace: team1
    framework: langgraph
    image: registry.cr-system.svc.cluster.local:5000/sandbox-agent:latest
    env:
      - name: LLM_API_BASE
        value: http://dockerhost:11434/v1
      - name: LLM_MODEL
        value: qwen2.5:3b
    security:
      profile: L4-sandbox  # Landlock + AuthBridge
    budget:
      max_tokens: 100000
      max_cost_usd: 1.0
```
