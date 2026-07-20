"""Patch hermes models.py to support custom_providers model resolution.

Upstream issue: NousResearch/hermes-agent#34500
"""

import pathlib

import hermes_cli

site = pathlib.Path(hermes_cli.__file__).parent
models_py = site / "models.py"

if not models_py.exists():
    print("models.py not found")
    exit(1)

src = models_py.read_text()

if "rossoctl patch" in src:
    print("Already patched")
    exit(0)

helper = '''

def _load_custom_providers():
    import yaml
    from pathlib import Path
    cfg = Path.home() / ".hermes" / "config.yaml"
    if cfg.exists():
        with open(cfg) as f:
            data = yaml.safe_load(f) or {}
        return data.get("custom_providers", [])
    return []

'''

patch = '''    # --- rossoctl patch: custom_providers model resolution (#34500) ---
    custom = _load_custom_providers()
    for cp in custom:
        if cp.get("name") == normalized:
            return cp.get("models", [])
    # --- end rossoctl patch ---
'''

# Insert helper AFTER all imports (find the first function def)
import re
first_def = re.search(r'\ndef [a-z_]+\(', src)
if first_def:
    insert_pos = first_def.start()
    src = src[:insert_pos] + helper + src[insert_pos:]

src = src.replace(
    'if normalized == "stepfun":',
    patch + '    if normalized == "stepfun":',
)
models_py.write_text(src)
print("Patched models.py for custom_providers")
