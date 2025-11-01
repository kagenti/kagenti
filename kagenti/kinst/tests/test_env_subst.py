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

import os
import json
import pytest
from kagenti.kinst.cli import load_env_file, substitute_env_vars


def make_vals(path, content):
    path.write_text(json.dumps(content))


def test_substitution_precedence_env_over_file(tmp_path, monkeypatch):
    # env var should take precedence over .env file
    os.environ["FOO"] = "fromenv"
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=fromfile")
    values = {"k": "${FOO}"}
    env_map = load_env_file(env_file)
    res = substitute_env_vars(values, env_map)
    assert res["k"] == "fromenv"
    del os.environ["FOO"]


def test_missing_var_raises(tmp_path):
    values = {"k": "${MISSING_VAR}"}
    with pytest.raises(RuntimeError):
        substitute_env_vars(values, {})


def test_allow_missing_leaves_placeholder(tmp_path):
    values = {"k": "before-${MISSING}-after"}
    res = substitute_env_vars(values, {}, allow_missing=True)
    assert res["k"] == "before-${MISSING}-after"


def test_nested_substitution(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("A=one\nB=two")
    env_map = load_env_file(env_file)
    vals = {"outer": {"list": ["x", "${A}", {"inner": "${B}"}]}}
    res = substitute_env_vars(vals, env_map)
    assert res["outer"]["list"][1] == "one"
    assert res["outer"]["list"][2]["inner"] == "two"
