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

from kagenti.kinst.cli import compute_execution_order


def test_file_order_preserved():
    comp = {
        "installables": [
            {"id": "a", "type": "helm", "name": "a", "release": "a"},
            {"id": "b", "type": "helm", "name": "b", "release": "b"},
            {"id": "c", "type": "helm", "name": "c", "release": "c"},
        ]
    }
    order = compute_execution_order(comp, {})
    ids = [n["id"] for n in order]
    assert ids == ["a", "b", "c"]


def test_depends_on_chain():
    comp = {
        "installables": [
            {"id": "istio-base", "type": "helm", "name": "ib", "release": "ib"},
            {
                "id": "cert-manager",
                "type": "kubectl-apply",
                "url": "http://example/x",
                "dependsOn": "istio-base",
            },
            {
                "id": "kagenti",
                "type": "helm",
                "name": "kag",
                "release": "kag",
                "dependsOn": "cert-manager",
            },
        ]
    }
    order = compute_execution_order(comp, {})
    ids = [n["id"] for n in order]
    assert ids == ["istio-base", "cert-manager", "kagenti"]


def test_missing_dep_raises():
    comp = {
        "installables": [
            {
                "id": "a",
                "type": "helm",
                "name": "a",
                "release": "a",
                "dependsOn": "does-not-exist",
            }
        ]
    }
    try:
        compute_execution_order(comp, {})
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "unknown component id" in str(e)


def test_cycle_detection():
    comp = {
        "installables": [
            {"id": "a", "type": "helm", "name": "a", "release": "a", "dependsOn": "c"},
            {"id": "b", "type": "helm", "name": "b", "release": "b", "dependsOn": "a"},
            {"id": "c", "type": "helm", "name": "c", "release": "c", "dependsOn": "b"},
        ]
    }
    try:
        compute_execution_order(comp, {})
        assert False, "expected RuntimeError due to cycle"
    except RuntimeError as e:
        assert "dependency cycle" in str(e)
