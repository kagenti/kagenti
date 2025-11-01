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


def test_kubectl_label_apply_and_delete(tmp_path, monkeypatch):
    calls = []

    def fake_run_cmd(cmd, input_data=None, check=True):
        # capture a copy of the command
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "run_cmd", fake_run_cmd)

    # prepare installables and values
    comp = {
        "installables": [
            {
                "id": "label-team1",
                "type": "kubectl-label",
                "namespace": "team1.namespace",
                "labels": {"team": "team1", "env": "dev"},
                "condition": "team1.enabled",
            }
        ]
    }

    env = tmp_path / "env"
    env.mkdir()
    comps = env / "installables.yaml"
    comps.write_text(json.dumps(comp))

    vals = env / "values.yaml"
    vals.write_text(json.dumps({"team1": {"enabled": True, "namespace": "team1-ns"}}))

    schema = env / "schema.json"
    make_schema(schema)

    # apply should call kubectl label namespace team1-ns team=team1 env=dev --overwrite --context ctx --dry-run=client
    cli.apply(
        installables=comps,
        values=vals,
        schema=schema,
        kube_context="ctx",
        dry_run=True,
        wait=False,
        timeout=None,
    )

    assert calls, "no kubectl calls captured"
    apply_cmd = calls[-1]
    assert apply_cmd[0] == "kubectl"
    assert apply_cmd[1] == "label"
    assert apply_cmd[2] == "namespace"
    assert apply_cmd[3] == "team1-ns"
    # labels may appear in any order depending on dict iteration; check presence
    assert any("team=team1" == a for a in apply_cmd[4:7])
    assert any("env=dev" == a for a in apply_cmd[4:7])
    assert "--overwrite" in apply_cmd
    assert "--context" in apply_cmd
    assert "ctx" in apply_cmd
    assert "--dry-run=client" in apply_cmd

    # clear calls and run delete
    calls.clear()
    cli.delete(
        installables=comps, values=vals, schema=schema, kube_context="ctx", dry_run=True
    )

    assert calls, "no kubectl calls captured for delete"
    del_cmd = calls[-1]
    assert del_cmd[0] == "kubectl"
    assert del_cmd[1] == "label"
    assert del_cmd[2] == "namespace"
    assert del_cmd[3] == "team1-ns"
    # deletion args end with key- forms
    assert any(arg.endswith("-") for arg in del_cmd[4:7])
    assert "--context" in del_cmd
    assert "ctx" in del_cmd
    assert "--dry-run=client" in del_cmd


def test_kubectl_label_no_override(tmp_path, monkeypatch):
    calls = []

    def fake_run_cmd(cmd, input_data=None, check=True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "run_cmd", fake_run_cmd)

    comp = {
        "installables": [
            {
                "id": "label-team1",
                "type": "kubectl-label",
                "namespace": "team1.namespace",
                "labels": {"team": "team1"},
                "override": False,
                "condition": "team1.enabled",
            }
        ]
    }

    env = tmp_path / "env"
    env.mkdir()
    comps = env / "installables.yaml"
    comps.write_text(json.dumps(comp))

    vals = env / "values.yaml"
    vals.write_text(json.dumps({"team1": {"enabled": True, "namespace": "team1-ns"}}))

    schema = env / "schema.json"
    make_schema(schema)

    cli.apply(
        installables=comps,
        values=vals,
        schema=schema,
        kube_context="ctx",
        dry_run=True,
        wait=False,
        timeout=None,
    )

    assert calls, "no kubectl calls captured"
    apply_cmd = calls[-1]
    assert "--overwrite" not in apply_cmd
