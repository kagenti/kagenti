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


def test_cli_wait_used_when_item_missing(tmp_path, monkeypatch):
    calls = []

    def fake_helm_upgrade_install(
        *,
        release,
        name,
        repository,
        chart_version,
        values_file,
        namespace,
        kube_context,
        dry_run,
        wait,
        timeout,
        repo_credentials=None,
    ):
        calls.append({"wait": wait})
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "helm_upgrade_install", fake_helm_upgrade_install)

    comp = {"installables": [{"id": "x", "type": "helm", "name": "x", "release": "x"}]}
    comps = tmp_path / "installables.yaml"
    comps.write_text(json.dumps(comp))
    vals = tmp_path / "values.yaml"
    vals.write_text("{}")
    schema = tmp_path / "schema.json"
    make_schema(schema)

    # call apply with CLI-level wait=True, item has no wait field
    cli.apply(
        installables=comps,
        values=vals,
        schema=schema,
        kube_context=None,
        dry_run=True,
        wait=True,
        timeout=None,
    )

    assert calls, "helm_upgrade_install was not called"
    assert calls[0]["wait"] is True


def test_item_overrides_cli_wait(tmp_path, monkeypatch):
    calls = []

    def fake_helm_upgrade_install(
        *,
        release,
        name,
        repository,
        chart_version,
        values_file,
        namespace,
        kube_context,
        dry_run,
        wait,
        timeout,
        repo_credentials=None,
    ):
        calls.append({"wait": wait})
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "helm_upgrade_install", fake_helm_upgrade_install)

    comp = {
        "installables": [
            {"id": "x", "type": "helm", "name": "x", "release": "x", "wait": False}
        ]
    }
    comps = tmp_path / "installables.yaml"
    comps.write_text(json.dumps(comp))
    vals = tmp_path / "values.yaml"
    vals.write_text("{}")
    schema = tmp_path / "schema.json"
    make_schema(schema)

    # CLI-level wait True but item explicitly sets wait False -> expect False
    cli.apply(
        installables=comps,
        values=vals,
        schema=schema,
        kube_context=None,
        dry_run=True,
        wait=True,
        timeout=None,
    )

    assert calls, "helm_upgrade_install was not called"
    assert calls[0]["wait"] is False
