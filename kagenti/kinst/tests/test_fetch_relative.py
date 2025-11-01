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

import json
from types import SimpleNamespace
from pathlib import Path

from kagenti.kinst import cli


def make_schema(path: Path):
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "installables": {
                "type": "array",
                "items": {"type": "object", "required": ["id", "type"]},
            }
        },
    }
    path.write_text(json.dumps(schema))


def test_kubectl_apply_resolves_relative_path(tmp_path, monkeypatch):
    # prepare directory structure: env/installables.yaml and env/manifests/foo.yaml
    env_dir = tmp_path / "env"
    env_dir.mkdir()
    manifests_dir = env_dir / "manifests"
    manifests_dir.mkdir()

    manifest_text = """apiVersion: v1
kind: ConfigMap
metadata:
  name: test-cm
data:
  key: value
"""
    manifest_file = manifests_dir / "foo.yaml"
    manifest_file.write_text(manifest_text)

    # installables referencing the relative path (relative to installables.yaml)
    comp = {
        "installables": [
            {
                "id": "local-manifest",
                "type": "kubectl-apply",
                "url": "manifests/foo.yaml",
                "injectNamespace": False,
            }
        ]
    }
    comps = env_dir / "installables.yaml"
    comps.write_text(json.dumps(comp))

    vals = env_dir / "values.yaml"
    vals.write_text("{}")

    schema = env_dir / "schema.json"
    make_schema(schema)

    captured = {}

    def fake_kubectl_apply(yaml_text: str, kube_context: None, dry_run: bool = True):
        captured["text"] = yaml_text
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "kubectl_apply", fake_kubectl_apply)

    # run apply (dry-run) using the installables file path; function should resolve manifests/foo.yaml
    cli.apply(
        installables=comps,
        values=vals,
        schema=schema,
        kube_context=None,
        dry_run=True,
        wait=False,
        timeout=None,
    )

    assert "text" in captured, "kubectl_apply was not called"
    assert (
        manifest_text.strip() in captured["text"].strip()
    ), "manifest content was not passed to kubectl_apply"
