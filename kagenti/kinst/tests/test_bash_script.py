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


def test_task_runs(tmp_path, monkeypatch):
    calls = []

    def fake_run_cmd(cmd, input_data=None, check=True):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(cli, "run_cmd", fake_run_cmd)

    env = tmp_path / "env"
    env.mkdir()
    scripts_dir = env / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "hello.sh"
    script.write_text("#!/bin/bash\necho hello\n")

    comp = {
        "installables": [
            {
                "id": "run-hello",
                "type": "task",
                "command": "scripts/hello.sh",
                "applyArgs": ["arg1", "arg2"],
                "condition": "run.enabled",
            }
        ]
    }

    comps = env / "installables.yaml"
    comps.write_text(json.dumps(comp))

    vals = env / "values.yaml"
    vals.write_text(json.dumps({"run": {"enabled": True}}))

    schema = env / "schema.json"
    make_schema(schema)

    # run apply (not dry-run) to exercise run_cmd invocation
    cli.apply(
        installables=comps,
        values=vals,
        schema=schema,
        dry_run=False,
        wait=False,
        timeout=None,
    )

    assert calls, "no script calls captured"
    cmd = calls[-1]
    assert cmd[0].endswith("hello.sh") or cmd[0] == "scripts/hello.sh"
    # script path should be included and args present
    assert "arg1" in cmd
    assert "arg2" in cmd
