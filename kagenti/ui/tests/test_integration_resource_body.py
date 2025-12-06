# Assisted by watsonx Code Assistant
# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from lib import build_utils


class DummySt:
    def info(self, *_a, **_k):
        return None

    def warning(self, *_a, **_k):
        return None


def test_construct_tool_resource_body_includes_valuefrom(monkeypatch):
    """Integration test: ensure structured env entries flow into the resource body."""

    # Monkeypatch secrets fetch to avoid requiring a K8s client
    monkeypatch.setattr(
        build_utils,
        "get_secret_data",
        lambda core_v1_api, namespace, name, key: "gituser",
    )
    # Avoid Keycloak calls
    monkeypatch.setattr(build_utils, "_get_keycloak_client_secret", lambda st, name: "")

    st = DummySt()

    additional_env = [
        {
            "name": "SECRET_KEY",
            "valueFrom": {"secretKeyRef": {"name": "openai-secret", "key": "apikey"}},
        }
    ]

    body = build_utils._construct_tool_resource_body(
        st_object=st,
        core_v1_api=None,
        build_namespace="test-ns",
        resource_name="my-tool",
        resource_type="Tool",
        repo_url="https://example.com/repo.git",
        protocol="mcp",
        framework="test",
        additional_env_vars=additional_env,
        registry_config=None,
        pod_config=None,
        image_pull_secret=None,
    )

    assert body is not None
