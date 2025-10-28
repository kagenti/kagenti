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

import types


def make_log_container():
    class C:
        def markdown(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    return C()


def make_message_placeholder():
    class P:
        def markdown(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    return P()


def make_chunk_root(event):
    # Simple wrapper object matching the structure used in the module
    class Resp:
        def __init__(self, result):
            self.result = result

    class Chunk:
        def __init__(self, root):
            self.root = root

        def model_dump_json(self, **kwargs):
            return "{}"

    return Chunk(Resp(event))
