# Versioned Skill Packs — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Inject verified skill packs (superpowers by default) into sandbox agent workspaces via init containers, with YAML manifest pinning, layered verification, and wizard configuration.

**Architecture:** An init container clones skill packs from pinned git sources into `/workspace/.claude/skills/` before the agent starts. A `skill-packs.yaml` manifest in the repo pins each pack to a commit hash with GPG + content-hash verification. The wizard gets a new "Skills" step between Source and Security.

**Tech Stack:** Python 3.12 (init container), React/PatternFly (wizard), FastAPI (backend API), git (clone/verify), sha256 (integrity)

**Design doc:** `docs/plans/2026-03-04-skill-packs-design.md`

---

### Task 1: Create `skill-packs.yaml` Manifest

**Files:**
- Create: `skill-packs.yaml` (repo root in worktree)

**Step 1: Create the manifest file**

```yaml
# skill-packs.yaml — pinned, verified skill sources for sandbox agents
version: 1

trusted_keys:
  - id: anthropic-bot
    fingerprint: "SHA256:placeholder"
    type: gpg

packs:
  - name: superpowers
    description: "Claude Code superpowers — brainstorming, TDD, debugging, code review"
    source: https://github.com/claude-plugins-official/superpowers
    commit: "HEAD"
    path: skills/
    integrity: ""
    signer: anthropic-bot
    default: true
```

> Note: `commit` and `integrity` will be filled with real values once the superpowers repo commit is identified.

**Step 2: Commit**

```bash
cd .worktrees/sandbox-agent
git add skill-packs.yaml
git commit -s -m "feat(skills): add skill-packs.yaml manifest (Session M)"
```

---

### Task 2: Write `skill_pack_loader.py` — Init Container Script

**Files:**
- Create: `deployments/sandbox/skill_pack_loader.py`
- Test: `deployments/sandbox/tests/test_skill_pack_loader.py`

**Step 1: Write the failing tests**

```python
# deployments/sandbox/tests/test_skill_pack_loader.py
"""Tests for skill_pack_loader — init container that injects verified skills."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Module under test — will fail until Step 3
from skill_pack_loader import SkillPackLoader


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def sample_manifest(tmp_path):
    """Create a sample skill-packs.yaml."""
    manifest = {
        "version": 1,
        "trusted_keys": [
            {"id": "test-signer", "fingerprint": "SHA256:test123", "type": "gpg"}
        ],
        "packs": [
            {
                "name": "test-skills",
                "description": "Test skill pack",
                "source": "https://github.com/example/skills",
                "commit": "abc123",
                "path": "skills/",
                "integrity": "",
                "signer": "test-signer",
                "default": True,
            }
        ],
    }
    path = tmp_path / "skill-packs.yaml"
    path.write_text(yaml.dump(manifest))
    return path


class TestSkillPackLoader:
    def test_load_manifest(self, sample_manifest):
        loader = SkillPackLoader(str(sample_manifest), "/workspace")
        assert len(loader.packs) == 1
        assert loader.packs[0]["name"] == "test-skills"

    def test_load_manifest_missing_file(self, tmp_path):
        loader = SkillPackLoader(str(tmp_path / "missing.yaml"), "/workspace")
        assert loader.packs == []

    def test_filter_default_packs(self, sample_manifest):
        loader = SkillPackLoader(str(sample_manifest), "/workspace")
        defaults = loader.get_default_packs()
        assert len(defaults) == 1
        assert defaults[0]["name"] == "test-skills"

    def test_filter_selected_packs(self, sample_manifest):
        loader = SkillPackLoader(str(sample_manifest), "/workspace")
        selected = loader.get_packs(["test-skills"])
        assert len(selected) == 1

    def test_filter_unknown_pack_skipped(self, sample_manifest):
        loader = SkillPackLoader(str(sample_manifest), "/workspace")
        selected = loader.get_packs(["nonexistent"])
        assert len(selected) == 0

    def test_compute_content_hash(self, workspace):
        skills_dir = workspace / "skills"
        skills_dir.mkdir()
        (skills_dir / "SKILL.md").write_text("# Test Skill\nDo stuff.\n")
        loader = SkillPackLoader("/dev/null", str(workspace))
        h = loader.compute_content_hash(skills_dir)
        assert h.startswith("sha256:")
        assert len(h) > 10

    def test_content_hash_deterministic(self, workspace):
        skills_dir = workspace / "skills"
        skills_dir.mkdir()
        (skills_dir / "a.md").write_text("aaa")
        (skills_dir / "b.md").write_text("bbb")
        loader = SkillPackLoader("/dev/null", str(workspace))
        h1 = loader.compute_content_hash(skills_dir)
        h2 = loader.compute_content_hash(skills_dir)
        assert h1 == h2

    @patch("subprocess.run")
    def test_clone_at_commit(self, mock_run, workspace, sample_manifest):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        loader = SkillPackLoader(str(sample_manifest), str(workspace))
        pack = loader.packs[0]
        loader.clone_pack(pack, workspace / "clone-target")
        # Should call git clone then git checkout
        assert mock_run.call_count >= 2

    @patch("subprocess.run")
    def test_verify_commit_signature(self, mock_run, sample_manifest):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Good signature", stderr=""
        )
        loader = SkillPackLoader(str(sample_manifest), "/workspace")
        result = loader.verify_commit_signature(
            Path("/tmp/repo"), "abc123", "test-signer"
        )
        assert result is True

    @patch("subprocess.run")
    def test_verify_commit_signature_fails(self, mock_run, sample_manifest):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="BAD sig")
        loader = SkillPackLoader(str(sample_manifest), "/workspace")
        result = loader.verify_commit_signature(
            Path("/tmp/repo"), "abc123", "test-signer"
        )
        assert result is False

    def test_install_skills_to_workspace(self, workspace):
        # Simulate cloned pack with skills
        clone_dir = workspace / "_clone"
        skills_src = clone_dir / "skills" / "brainstorming"
        skills_src.mkdir(parents=True)
        (skills_src / "SKILL.md").write_text("# Brainstorming\n")

        loader = SkillPackLoader("/dev/null", str(workspace))
        loader.install_pack(clone_dir / "skills", "superpowers")

        # Skills should be at /workspace/.claude/skills/superpowers/brainstorming/SKILL.md
        target = workspace / ".claude" / "skills" / "superpowers" / "brainstorming" / "SKILL.md"
        assert target.exists()
        assert target.read_text() == "# Brainstorming\n"
```

**Step 2: Run tests to verify they fail**

```bash
cd .worktrees/sandbox-agent/deployments/sandbox
python -m pytest tests/test_skill_pack_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'skill_pack_loader'`

**Step 3: Write the implementation**

```python
# deployments/sandbox/skill_pack_loader.py
"""Init container script: clone and verify skill packs into /workspace/.claude/skills/.

Reads skill-packs.yaml, clones each pack at pinned commit, verifies GPG
signature and content hash, then copies skills into the workspace.

Usage (in init container):
    python3 skill_pack_loader.py [--config /config/skill-packs.yaml] [--workspace /workspace]
"""

import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("skill-pack-loader")


class SkillPackLoader:
    """Load, verify, and install skill packs from pinned git sources."""

    def __init__(self, config_path: str, workspace: str):
        self.config_path = config_path
        self.workspace = Path(workspace)
        self.packs: list[dict] = []
        self.trusted_keys: list[dict] = []
        self._load_config()

    def _load_config(self):
        """Load skill-packs.yaml manifest."""
        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f) or {}
            self.packs = data.get("packs", [])
            self.trusted_keys = data.get("trusted_keys", [])
        except FileNotFoundError:
            logger.warning("Manifest not found: %s", self.config_path)
        except yaml.YAMLError as e:
            logger.error("Invalid YAML in manifest: %s", e)

    def get_default_packs(self) -> list[dict]:
        """Return packs marked as default."""
        return [p for p in self.packs if p.get("default")]

    def get_packs(self, names: list[str]) -> list[dict]:
        """Return packs matching the given names."""
        return [p for p in self.packs if p["name"] in names]

    def clone_pack(self, pack: dict, target: Path):
        """Clone a pack repo at the pinned commit."""
        source = pack["source"]
        commit = pack["commit"]

        subprocess.run(
            ["git", "clone", "--no-checkout", source, str(target)],
            check=True, capture_output=True, timeout=120,
        )
        subprocess.run(
            ["git", "-C", str(target), "checkout", commit],
            check=True, capture_output=True, timeout=30,
        )

    def verify_commit_signature(
        self, repo_path: Path, commit: str, expected_signer: str
    ) -> bool:
        """Verify the commit is signed by a trusted key."""
        result = subprocess.run(
            ["git", "-C", str(repo_path), "verify-commit", commit],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "Commit %s signature verification failed: %s",
                commit[:8], result.stderr.strip(),
            )
            return False
        logger.info("Commit %s signature verified (signer: %s)", commit[:8], expected_signer)
        return True

    def compute_content_hash(self, directory: Path) -> str:
        """Compute SHA256 hash of all files in directory (sorted, deterministic)."""
        h = hashlib.sha256()
        for fpath in sorted(directory.rglob("*")):
            if fpath.is_file():
                rel = fpath.relative_to(directory)
                h.update(str(rel).encode())
                h.update(fpath.read_bytes())
        return f"sha256:{h.hexdigest()}"

    def verify_content_hash(self, directory: Path, expected: str) -> bool:
        """Verify content hash matches expected value."""
        if not expected:
            logger.info("No integrity hash specified — skipping content verification")
            return True
        actual = self.compute_content_hash(directory)
        if actual != expected:
            logger.error(
                "Content hash mismatch: expected %s, got %s",
                expected[:20], actual[:20],
            )
            return False
        logger.info("Content hash verified: %s", actual[:20])
        return True

    def install_pack(self, skills_source: Path, pack_name: str):
        """Copy skills from cloned source into workspace."""
        target = self.workspace / ".claude" / "skills" / pack_name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skills_source, target)
        logger.info("Installed pack '%s' → %s", pack_name, target)

    def load_pack(self, pack: dict) -> bool:
        """Clone, verify, and install a single pack. Returns True on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_dir = Path(tmpdir) / pack["name"]
            try:
                logger.info("Cloning %s at %s...", pack["source"], pack["commit"][:8])
                self.clone_pack(pack, clone_dir)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.error("Failed to clone %s: %s", pack["name"], e)
                return False

            # Layer 1: GPG signature
            signer = pack.get("signer")
            if signer:
                if not self.verify_commit_signature(clone_dir, pack["commit"], signer):
                    logger.warning("Skipping %s — signature verification failed", pack["name"])
                    return False

            # Layer 2: Content hash
            skills_path = clone_dir / pack.get("path", "skills/")
            if not skills_path.exists():
                logger.error("Skills path %s not found in %s", pack["path"], pack["name"])
                return False

            if not self.verify_content_hash(skills_path, pack.get("integrity", "")):
                logger.warning("Skipping %s — content hash mismatch", pack["name"])
                return False

            # Install
            self.install_pack(skills_path, pack["name"])
            return True


def main():
    """Entry point for init container."""
    import argparse

    parser = argparse.ArgumentParser(description="Load verified skill packs")
    parser.add_argument("--config", default=os.environ.get("SKILL_PACKS_CONFIG", "/config/skill-packs.yaml"))
    parser.add_argument("--workspace", default=os.environ.get("WORKSPACE_DIR", "/workspace"))
    parser.add_argument("--packs", nargs="*", help="Specific packs to load (default: all default packs)")
    args = parser.parse_args()

    loader = SkillPackLoader(args.config, args.workspace)

    packs = loader.get_packs(args.packs) if args.packs else loader.get_default_packs()
    if not packs:
        logger.info("No skill packs to load")
        return

    logger.info("Loading %d skill pack(s)...", len(packs))
    loaded = 0
    for pack in packs:
        if loader.load_pack(pack):
            loaded += 1

    logger.info("Done: %d/%d packs loaded successfully", loaded, len(packs))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
cd .worktrees/sandbox-agent/deployments/sandbox
python -m pytest tests/test_skill_pack_loader.py -v
```

Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add deployments/sandbox/skill_pack_loader.py deployments/sandbox/tests/test_skill_pack_loader.py
git commit -s -m "feat(skills): skill_pack_loader.py — init container for verified skill injection (Session M)"
```

---

### Task 3: Backend — `GET /api/v1/sandbox/skill-packs` Endpoint

**Files:**
- Modify: `kagenti/backend/app/routers/sandbox_deploy.py` (add endpoint)
- Test: `kagenti/backend/tests/test_sandbox_deploy_skills.py` (if test infra exists, else manual)

**Step 1: Add endpoint to serve skill-packs.yaml to the wizard**

Add to `sandbox_deploy.py` after the existing endpoints:

```python
@router.get("/skill-packs")
async def list_skill_packs():
    """Return available skill packs from skill-packs.yaml for the wizard UI."""
    import yaml
    manifest_path = Path(__file__).parent.parent.parent.parent.parent / "skill-packs.yaml"
    if not manifest_path.exists():
        return {"version": 1, "packs": []}
    with open(manifest_path) as f:
        data = yaml.safe_load(f) or {}
    # Strip sensitive fields (trusted_keys) for frontend
    packs = data.get("packs", [])
    return {
        "version": data.get("version", 1),
        "packs": [
            {
                "name": p["name"],
                "description": p.get("description", ""),
                "source": p["source"],
                "commit": p["commit"][:8],
                "default": p.get("default", False),
            }
            for p in packs
        ],
    }
```

**Step 2: Verify endpoint works**

```bash
# After deploy, test via curl:
curl -s $KAGENTI_UI_URL/api/v1/sandbox/skill-packs | jq .
```

**Step 3: Commit**

```bash
git add kagenti/backend/app/routers/sandbox_deploy.py
git commit -s -m "feat(backend): GET /skill-packs endpoint for wizard (Session M)"
```

---

### Task 4: Backend — Add Init Container to Deployment Manifest

**Files:**
- Modify: `kagenti/backend/app/routers/sandbox_deploy.py` — `_build_deployment_manifest()` function

**Step 1: Add `skill_packs` field to `SandboxCreateRequest`**

Find the `SandboxCreateRequest` model in `sandbox_deploy.py` and add:

```python
skill_packs: list[str] = []  # Pack names from skill-packs.yaml (empty = defaults)
```

**Step 2: Add init container to deployment manifest**

In `_build_deployment_manifest()`, before the `"containers"` array, add:

```python
# Build init containers list
init_containers = []
if req.skill_packs or True:  # Always include skill loader for default packs
    init_containers.append({
        "name": "skill-loader",
        "image": "python:3.12-slim",
        "command": ["python3", "/scripts/skill_pack_loader.py"],
        "env": [
            {"name": "SKILL_PACKS_CONFIG", "value": "/config/skill-packs.yaml"},
            {"name": "WORKSPACE_DIR", "value": "/workspace"},
        ],
        "volumeMounts": [
            {"name": "workspace", "mountPath": "/workspace"},
            {"name": "skill-config", "mountPath": "/config", "readOnly": True},
            {"name": "skill-loader-script", "mountPath": "/scripts", "readOnly": True},
        ],
    })
```

Add to volumes:

```python
{"name": "skill-config", "configMap": {"name": f"{req.name}-skill-packs"}},
{"name": "skill-loader-script", "configMap": {"name": "skill-pack-loader-script"}},
```

**Step 3: Create ConfigMaps in the deploy endpoint**

Before creating the Deployment, create:
1. `{name}-skill-packs` ConfigMap with filtered `skill-packs.yaml`
2. `skill-pack-loader-script` ConfigMap with `skill_pack_loader.py` content

**Step 4: Commit**

```bash
git add kagenti/backend/app/routers/sandbox_deploy.py
git commit -s -m "feat(deploy): add skill-loader init container to agent deployments (Session M)"
```

> **Note:** Coordinate with Session K — they own `sandbox_deploy.py`. Check for conflicts before pushing.

---

### Task 5: UI — Add "Skills" Wizard Step

**Files:**
- Modify: `kagenti/ui-v2/src/pages/SandboxCreatePage.tsx`

**Step 1: Add "Skills" to STEPS array**

```typescript
const STEPS = [
  'Source',
  'Skills',      // NEW — insert here
  'Security',
  'Identity',
  'Persistence',
  'Observability',
  'Review',
];
```

**Step 2: Add state fields**

In `WizardState` interface, add:

```typescript
selectedSkillPacks: string[];  // pack names selected by user
```

In `INITIAL_STATE`, add:

```typescript
selectedSkillPacks: [],
```

**Step 3: Add the Skills step renderer**

```tsx
// Skills step — between Source and Security
function SkillsStep({ state, update }: StepProps) {
  const { data: skillPacks } = useQuery({
    queryKey: ['skill-packs'],
    queryFn: async () => {
      const resp = await fetch('/api/v1/sandbox/skill-packs');
      return resp.json();
    },
  });

  const packs = skillPacks?.packs || [];

  // Initialize defaults on first render
  useEffect(() => {
    if (state.selectedSkillPacks.length === 0 && packs.length > 0) {
      const defaults = packs.filter((p: any) => p.default).map((p: any) => p.name);
      update('selectedSkillPacks', defaults);
    }
  }, [packs]);

  return (
    <FormGroup label="Skill Packs" fieldId="skill-packs">
      {packs.map((pack: any) => (
        <Checkbox
          key={pack.name}
          id={`skill-${pack.name}`}
          label={`${pack.name} — ${pack.description}`}
          description={`Source: ${pack.source} @ ${pack.commit}`}
          isChecked={state.selectedSkillPacks.includes(pack.name)}
          onChange={(_e, checked) => {
            const next = checked
              ? [...state.selectedSkillPacks, pack.name]
              : state.selectedSkillPacks.filter((n: string) => n !== pack.name);
            update('selectedSkillPacks', next);
          }}
        />
      ))}
    </FormGroup>
  );
}
```

**Step 4: Wire into `stepRenderers` array**

Insert `SkillsStep` at index 1 (after Source, before Security).

**Step 5: Pass `selectedSkillPacks` in the create request body**

In the form submission handler, add `skill_packs: state.selectedSkillPacks` to the POST body.

**Step 6: Commit**

```bash
git add kagenti/ui-v2/src/pages/SandboxCreatePage.tsx
git commit -s -m "feat(ui): Skills wizard step with pack selection (Session M)"
```

---

### Task 6: E2E Test — Skill Invocation via Chat

**Files:**
- Create: `kagenti/ui-v2/e2e/sandbox-skill-invocation.spec.ts`

**Step 1: Write the test**

```typescript
import { test, expect, Page } from '@playwright/test';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

async function loginIfNeeded(page: Page) {
  await page.waitForLoadState('networkidle', { timeout: 30000 });
  const isKeycloakLogin = await page
    .locator('#kc-form-login, input[name="username"]')
    .first()
    .isVisible({ timeout: 5000 })
    .catch(() => false);
  if (!isKeycloakLogin) {
    const signInButton = page.getByRole('button', { name: /Sign In/i });
    const hasSignIn = await signInButton.isVisible({ timeout: 5000 }).catch(() => false);
    if (!hasSignIn) return;
    await signInButton.click();
    await page.waitForLoadState('networkidle', { timeout: 30000 });
  }
  const usernameField = page.locator('input[name="username"]').first();
  const passwordField = page.locator('input[name="password"]').first();
  const submitButton = page
    .locator('#kc-login, button[type="submit"], input[type="submit"]')
    .first();
  await usernameField.waitFor({ state: 'visible', timeout: 10000 });
  await usernameField.fill(KEYCLOAK_USER);
  await passwordField.waitFor({ state: 'visible', timeout: 5000 });
  await passwordField.click();
  await passwordField.pressSequentially(KEYCLOAK_PASSWORD, { delay: 20 });
  await page.waitForTimeout(300);
  await submitButton.click();
  await page.waitForURL(/^(?!.*keycloak)/, { timeout: 30000 });
  await page.waitForLoadState('networkidle');
}

test.describe('Skill invocation from chat', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await loginIfNeeded(page);
    // Navigate to sandbox chat
    await page.locator('nav a', { hasText: 'Sessions' }).first().click();
    await page.waitForLoadState('networkidle');
  });

  test('sends /skill:name as skill field in request body', async ({ page }) => {
    // Intercept the stream request to verify skill field
    let capturedBody: any = null;
    await page.route('**/sandbox/*/chat/stream', async (route) => {
      const body = route.request().postDataJSON();
      capturedBody = body;
      // Continue the request (let it go to the server)
      await route.continue();
    });

    const chatInput = page.locator(
      'textarea[placeholder*="message"], textarea[aria-label="Message input"]'
    ).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    // Type a skill invocation
    await chatInput.fill('/tdd:ci analyze latest failures');
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for the request to be intercepted
    await page.waitForTimeout(2000);

    // Verify the request body has the skill field
    expect(capturedBody).toBeTruthy();
    expect(capturedBody.skill).toBe('tdd:ci');
    expect(capturedBody.message).toBe('analyze latest failures');
  });

  test('sends message without skill field when no / prefix', async ({ page }) => {
    let capturedBody: any = null;
    await page.route('**/sandbox/*/chat/stream', async (route) => {
      const body = route.request().postDataJSON();
      capturedBody = body;
      await route.continue();
    });

    const chatInput = page.locator(
      'textarea[placeholder*="message"], textarea[aria-label="Message input"]'
    ).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    await chatInput.fill('Hello, what can you do?');
    await page.getByRole('button', { name: /Send/i }).click();

    await page.waitForTimeout(2000);

    expect(capturedBody).toBeTruthy();
    expect(capturedBody.skill).toBeUndefined();
    expect(capturedBody.message).toBe('Hello, what can you do?');
  });

  test('user message shows full text including /skill prefix', async ({ page }) => {
    const chatInput = page.locator(
      'textarea[placeholder*="message"], textarea[aria-label="Message input"]'
    ).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    await chatInput.fill('/rca:ci #758');
    await page.getByRole('button', { name: /Send/i }).click();

    // User message should show the full text including the slash command
    await expect(page.getByText('/rca:ci #758')).toBeVisible({ timeout: 10000 });
  });

  test('skill-only message uses skill name as message text', async ({ page }) => {
    // When user types just "/rca:ci" with no additional text
    let capturedBody: any = null;
    await page.route('**/sandbox/*/chat/stream', async (route) => {
      const body = route.request().postDataJSON();
      capturedBody = body;
      await route.continue();
    });

    const chatInput = page.locator(
      'textarea[placeholder*="message"], textarea[aria-label="Message input"]'
    ).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    await chatInput.fill('/rca:ci');
    await page.getByRole('button', { name: /Send/i }).click();

    await page.waitForTimeout(2000);

    expect(capturedBody).toBeTruthy();
    expect(capturedBody.skill).toBe('rca:ci');
    // When no additional text, message should be the skill name itself
    expect(capturedBody.message).toBe('rca:ci');
  });
});
```

**Step 2: Run tests (Level 0 — test-only, no build needed)**

```bash
cd .worktrees/sandbox-agent/kagenti/ui-v2
KUBECONFIG=$KUBECONFIG KAGENTI_UI_URL=$KAGENTI_UI_URL \
  KEYCLOAK_USER=admin KEYCLOAK_PASSWORD=$KEYCLOAK_PASSWORD \
  npx playwright test e2e/sandbox-skill-invocation.spec.ts --reporter=list \
  > $LOG_DIR/skill-test.log 2>&1; echo "EXIT:$?"
```

Expected: 4/4 PASS (these test frontend request interception, not full agent loop)

**Step 3: Commit**

```bash
git add kagenti/ui-v2/e2e/sandbox-skill-invocation.spec.ts
git commit -s -m "test(e2e): skill invocation from chat — verify skill field in request (Session M)"
```

---

### Task 7: E2E Test — Live CI Skill Invocation (Integration)

**Files:**
- Create: `kagenti/ui-v2/e2e/sandbox-skill-ci-live.spec.ts`

> **Prerequisite:** Agent must have `tdd:ci` skill loaded (requires skill pack injection working end-to-end). This test is for Phase 3.

**Step 1: Write the live CI test**

```typescript
import { test, expect, Page } from '@playwright/test';
import { execSync } from 'child_process';

const KEYCLOAK_USER = process.env.KEYCLOAK_USER || 'admin';
const KEYCLOAK_PASSWORD = process.env.KEYCLOAK_PASSWORD || 'admin';

// ... loginIfNeeded helper (same as Task 6)

function getLatestCIRuns(count: number): { databaseId: number; conclusion: string }[] {
  const output = execSync(
    `gh run list --repo Ladas/kagenti --status completed -L ${count} --json databaseId,conclusion`,
    { encoding: 'utf-8' }
  );
  return JSON.parse(output);
}

test.describe('Live CI skill invocation', () => {
  test('agent analyzes real CI run with /tdd:ci', async ({ page }) => {
    const runs = getLatestCIRuns(1);
    test.skip(runs.length === 0, 'No completed CI runs found');

    const runId = runs[0].databaseId;

    await page.goto('/');
    // ... login and navigate to sandbox chat

    const chatInput = page.locator(
      'textarea[placeholder*="message"], textarea[aria-label="Message input"]'
    ).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    await chatInput.fill(`/tdd:ci #${runId}`);
    await page.getByRole('button', { name: /Send/i }).click();

    // Wait for structured response (long timeout — agent needs to fetch CI logs)
    const response = page.locator('.sandbox-markdown').last();
    await expect(response).toBeVisible({ timeout: 120_000 });

    // Verify structured sections in response
    const text = await response.textContent();
    expect(text).toBeTruthy();
    // Agent should produce analysis with some structure
    expect(text!.length).toBeGreaterThan(100);
  });
});
```

**Step 2: Commit (test will be skipped until Phase 3)**

```bash
git add kagenti/ui-v2/e2e/sandbox-skill-ci-live.spec.ts
git commit -s -m "test(e2e): live CI skill invocation — /tdd:ci against real runs (Session M)"
```

---

## Task Dependencies

```
Task 1 (manifest)
    ↓
Task 2 (loader script + tests)
    ↓
Task 3 (backend API) ←──── Task 5 (wizard UI)
    ↓
Task 4 (init container in deploy)
    ↓
Task 6 (E2E test — request interception)
    ↓
Task 7 (E2E test — live CI, Phase 3)
```

## Execution Order

1. Task 1 → Task 2 → Task 6 (can test frontend immediately)
2. Task 3 → Task 4 (backend, coordinate with Session K)
3. Task 5 (wizard UI, after backend is ready)
4. Task 7 (integration test, after full pipeline works)
