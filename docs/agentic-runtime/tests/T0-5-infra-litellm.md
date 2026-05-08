# LiteLLM Infrastructure

> **Test file:** `kagenti/tests/e2e/openshell/test_T0_5_infra_litellm.py`
> **Tests:** 11

## What This Tests

Validates LiteLLM proxy configuration, security posture, Istio waypoint infrastructure, and Anthropic Messages API passthrough. Covers three areas: (1) secure config -- no plaintext API keys in ConfigMaps, secrets exist, deployment uses `secretKeyRef`, correct provider prefix (`hosted_vllm/` or `ollama/`), and Anthropic translation settings present; (2) Istio waypoint -- namespaces with `istio.io/use-waypoint` label have a matching Gateway resource and running waypoint proxy pod; (3) model routing -- LiteLLM correctly translates Anthropic Messages API requests, lists Claude model aliases, and routes requests to each configured model.

## Test Functions

- `test_configmap_no_plaintext_api_keys` -- LiteLLM ConfigMap uses `os.environ/VAR_NAME` references for API keys (or no `api_key` lines in Ollama mode).
- `test_litemaas_secret_exists` -- The `litemaas-credentials` Kubernetes Secret exists and contains a non-empty `api-key`.
- `test_litellm_deployment_uses_secret_ref` -- LiteLLM Deployment mounts `LITEMAAS_API_KEY` via `secretKeyRef` (not a literal value).
- `test_litellm_uses_correct_provider` -- Model config uses `hosted_vllm/` or `ollama/` provider prefix, not `openai/`.
- `test_litellm_anthropic_settings` -- Config includes `use_chat_completions_url_for_anthropic_messages` and `drop_params` for Claude Code compatibility.
- `test_waypoint_exists_if_labeled[namespace]` -- Namespaces with `istio.io/use-waypoint` label have a matching waypoint Gateway resource.
- `test_waypoint_pod_running` -- Waypoint proxy pod in team1 is in Running phase.
- `test_anthropic_messages_api_returns_response` -- LiteLLM `/v1/messages` endpoint returns a valid Anthropic-format response with `type=message`.
- `test_claude_model_alias_in_model_list` -- LiteLLM `/v1/models` lists the `claude-sonnet-4-20250514` alias.
- `test_litellm_model_routing__responds[model]` -- Each configured model returns a valid chat completion response through LiteLLM.
- `test_litellm_model_routing__all_models_in_list` -- All models from `OPENSHELL_LLM_MODELS` appear in the LiteLLM model list.
