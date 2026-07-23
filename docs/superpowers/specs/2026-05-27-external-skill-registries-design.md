---
draft: true       # excluded from https://www.rossoctl.dev/
---

# External Skill Registries — Design Spec

**Date:** 2026-05-27  
**Status:** Approved  
**Feature flag:** `rossoctl_feature_flag_external_skills` (default: `False`)

---

## Overview

Rossoctl skills are currently stored as Kubernetes ConfigMaps containing the full skill file content. This spec extends the skill system to support **external skill registries**: a lightweight ConfigMap variant that holds only a pointer (URL + metadata) to a skill in a remote registry. At agent pod startup, an init container fetches the skill content from the registry and writes it to a shared volume — the agent container mounts the result identically to a local skill.

The initial target registry is [skillberry-store](https://github.ibm.com/skillberry/skillberry-store/), which serves skill archives via a REST API returning `tar.gz` bundles.

---

## Goals

- Allow operators to register external skill references without uploading file content.
- At agent startup, fetch skill content from the registry and mount it transparently to the agent — no agent framework changes.
- Shell scripts inside an `alpine:3` init container handle all registry-specific logic (download, retry, extraction, future auth). No new container images required.
- External and local skills are unified in the UI catalog; external skills show a distinguishing badge.
- All new behaviour is gated behind a feature flag (`rossoctl_feature_flag_external_skills`).

## Non-Goals

- Caching fetched skill content across restarts (no local caching — registry must be reachable at pod start).
- Authentication to registries (deferred; scripts are designed to accept credentials via env vars when needed).
- Helm-chart-level delivery of the fetcher scripts ConfigMap (backend creates it lazily).

---

## Data Model

### External Skill Reference ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: <sanitized-skill-name>       # e.g. skillberry-code-review
  namespace: <team-namespace>        # team1 / team2
  labels:
    rossoctl.io/type: skill
    rossoctl.io/source: external       # distinguishes from local skills
    rossoctl.io/registry-type: skillberry  # selects fetcher script
    rossoctl.io/category: <category>   # optional
    app.kubernetes.io/managed-by: rossoctl-ui
  annotations:
    rossoctl.io/display-name: "Code Review"
    rossoctl.io/description: "Reviews code for quality and style"
    rossoctl.io/registry-url: "https://skillberry.example.com"
    rossoctl.io/registry-skill-name: "code-review"
    rossoctl.io/registry-skill-version: "1.2.0"   # optional; "latest" if absent
    rossoctl.io/origin: "https://skillberry.example.com/skills/code-review"
    rossoctl.io/usage-count: "0"
data: {}   # intentionally empty — no content stored locally
```

**New label/annotation constants** (added to `constants.py`):

| Constant | Value |
|---|---|
| `SKILL_SOURCE_LABEL` | `rossoctl.io/source` |
| `SKILL_SOURCE_EXTERNAL` | `external` |
| `SKILL_SOURCE_LOCAL` | `local` (for future explicit tagging; currently absence of label means local) |
| `SKILL_REGISTRY_TYPE_LABEL` | `rossoctl.io/registry-type` |
| `SKILL_REGISTRY_URL_ANNOTATION` | `rossoctl.io/registry-url` |
| `SKILL_REGISTRY_SKILL_NAME_ANNOTATION` | `rossoctl.io/registry-skill-name` |
| `SKILL_REGISTRY_SKILL_VERSION_ANNOTATION` | `rossoctl.io/registry-skill-version` |
| `SKILL_FETCHER_SCRIPTS_CM` | `rossoctl-skill-fetcher-scripts` |
| `SKILL_FETCHER_IMAGE` | `alpine:3` |

---

## Fetcher Scripts ConfigMap

The backend ensures a ConfigMap named `rossoctl-skill-fetcher-scripts` exists in **each namespace where an agent with external skills is deployed**. It is created or overwritten by the backend at agent-creation time (idempotent upsert). It is labeled `app.kubernetes.io/managed-by: rossoctl` so it is clearly Rossoctl-owned.

Each key in `data` is `<registry-type>.sh`. The script receives the following environment variables from the init container spec:

| Variable | Source |
|---|---|
| `REGISTRY_URL` | `rossoctl.io/registry-url` annotation |
| `SKILL_NAME` | `rossoctl.io/registry-skill-name` annotation |
| `SKILL_VERSION` | `rossoctl.io/registry-skill-version` annotation (default: `latest`) |
| `TARGET_DIR` | Computed by backend: `/app/skills/<sanitized-name>` |

### `skillberry.sh`

```sh
#!/bin/sh
set -e

SKILL_VERSION="${SKILL_VERSION:-latest}"
URL="${REGISTRY_URL}/api/v1/skills/${SKILL_NAME}/${SKILL_VERSION}/archive"

echo "Fetching ${SKILL_NAME}@${SKILL_VERSION} from ${URL}"

RETRIES=3
DELAY=2
for i in $(seq 1 $RETRIES); do
    if curl -fsSL -o /tmp/skill.tar.gz "${URL}"; then
        break
    fi
    if [ "$i" -eq "$RETRIES" ]; then
        echo "FATAL: fetch failed after ${RETRIES} attempts"
        exit 1
    fi
    echo "Attempt ${i} failed; retrying in ${DELAY}s..."
    sleep $DELAY
done

mkdir -p "${TARGET_DIR}"
tar -xzf /tmp/skill.tar.gz -C "${TARGET_DIR}"
echo "OK: ${SKILL_NAME}@${SKILL_VERSION} → ${TARGET_DIR}"
```

### `generic.sh`

Fallback for any registry type whose dedicated script is missing. Assumes the registry URL already encodes the full download endpoint.

```sh
#!/bin/sh
set -e

echo "Fetching skill from ${REGISTRY_URL}"

RETRIES=3
DELAY=2
for i in $(seq 1 $RETRIES); do
    if curl -fsSL -o /tmp/skill.tar.gz "${REGISTRY_URL}"; then
        break
    fi
    if [ "$i" -eq "$RETRIES" ]; then
        echo "FATAL: fetch failed after ${RETRIES} attempts"
        exit 1
    fi
    echo "Attempt ${i} failed; retrying in ${DELAY}s..."
    sleep $DELAY
done

mkdir -p "${TARGET_DIR}"
tar -xzf /tmp/skill.tar.gz -C "${TARGET_DIR}"
echo "OK: ${REGISTRY_URL} → ${TARGET_DIR}"
```

Adding a new registry type in the future requires only adding a new `<type>.sh` key — no backend code changes.

---

## Runtime: Pod Spec Changes

When an agent references a skill, the backend looks up the skill's ConfigMap to determine whether it is local or external. The agent's mount path `/app/skills/<name>` is identical in both cases; the agent process sees no difference.

### Local skill (existing — unchanged)

```
Volume:        configMap {name: my-local-skill}
Mount (main):  /app/skills/my-local-skill  readOnly=true
InitContainer: none
```

### External skill (new)

```
Volumes:
  skill-ext-<i>:       emptyDir {}
  fetcher-scripts-vol: configMap {name: rossoctl-skill-fetcher-scripts}

InitContainer: fetch-skill-<i>
  image:   alpine:3
  command:
    - /bin/sh
    - -c
    - |
      SCRIPT=/fetcher-scripts/${REGISTRY_TYPE}.sh
      [ -f "$SCRIPT" ] || SCRIPT=/fetcher-scripts/generic.sh
      /bin/sh "$SCRIPT"
  env:
    REGISTRY_TYPE: <rossoctl.io/registry-type label>
    REGISTRY_URL:  <rossoctl.io/registry-url>
    SKILL_NAME:    <rossoctl.io/registry-skill-name>
    SKILL_VERSION: <rossoctl.io/registry-skill-version>  # or "latest"
    TARGET_DIR:    /app/skills/<sanitized-name>
  volumeMounts:
    skill-ext-<i>:       /app/skills/<sanitized-name>   readOnly=false
    fetcher-scripts-vol: /fetcher-scripts                readOnly=true

Mount (main):  skill-ext-<i> → /app/skills/<sanitized-name>  readOnly=true
```

If the registry is unreachable, the init container exits non-zero and the pod fails to start (hard dependency — intentional).

The `SKILL_FOLDERS` env var on the main container remains a comma-separated list of all mount paths (local + external), unchanged.

One `fetcher-scripts-vol` volume is shared across all external skill init containers in the same pod.

---

## Backend Changes

### `rossoctl/backend/app/core/constants.py`

Add the constants listed in the Data Model section above.

### `rossoctl/backend/app/core/config.py`

```python
# Gate all external registry skill behaviour
rossoctl_feature_flag_external_skills: bool = False
```

### `rossoctl/backend/app/routers/config.py`

Expose the new flag in the `GET /api/config/features` response.

### `rossoctl/backend/app/routers/skills.py`

**New Pydantic models:**

```python
class CreateExternalSkillRequest(BaseModel):
    name: str
    namespace: str
    description: str = ""
    category: str = ""
    registryType: str          # e.g. "skillberry"
    registryUrl: str
    registrySkillName: str
    registrySkillVersion: str = "latest"
    origin: str = ""

class ExternalSkillInfo(BaseModel):
    """Extra fields present only on external skills."""
    source: str              # always "external"
    registryType: str
    registryUrl: str
    registrySkillName: str
    registrySkillVersion: str
```

**Updated `Skill` model:** add optional `source: str | None` and `externalInfo: ExternalSkillInfo | None`.

**New helper `_is_external(cm)`:** returns `True` if the ConfigMap has label `rossoctl.io/source=external`.

**New helper `_configmap_to_external_skill_info(cm)`:** builds `ExternalSkillInfo` from annotations.

**Updated `_configmap_to_skill()`:** populate `source` and `externalInfo` when `_is_external(cm)`.

**Updated `_configmap_to_skill_detail()`:** for external skills, `files` is empty and `dataKeys` is empty; registry metadata is populated instead.

**New endpoint `POST /skills/external`** (requires `ROLE_OPERATOR`, feature-flagged):

```python
@router.post("/skills/external", ...)
async def create_external_skill(request: CreateExternalSkillRequest, ...):
    # Validate registryType is non-empty
    # Sanitize resource name
    # Build ConfigMap with labels/annotations from request
    # Create in K8s
    # Return CreateSkillResponse
```

### `rossoctl/backend/app/routers/agents.py`

**New helper `_is_skill_external(kube, namespace, skill_name) -> bool`:** looks up the ConfigMap, returns `True` if it has `rossoctl.io/source=external`.

**New helper `_ensure_fetcher_scripts_cm(kube, namespace)`:** creates or updates the `rossoctl-skill-fetcher-scripts` ConfigMap in the given namespace with the embedded shell scripts.

**New helper `_get_external_skill_init_containers(external_skills, namespace) -> tuple[list, list, list, str | None]`:** returns `(volumes, init_containers, main_mounts, skill_paths_fragment)` for all external skills.

**Updated `_get_linked_skill_mounts()`:** split into local and external paths. Before returning, call `_ensure_fetcher_scripts_cm` if any external skills are present.

**Updated `_load_agent_skill_summaries()`:** no change to the K8s query (label selector already matches external refs); `ExternalSkillInfo` is included in the annotation map that is already returned.

---

## API Changes Summary

| Method | Path | Change |
|---|---|---|
| `POST` | `/skills/external` | New — create external skill reference |
| `GET` | `/skills` | `Skill` response gains optional `source`, `externalInfo` fields |
| `GET` | `/skills/{ns}/{name}` | `SkillDetail.files` is empty for external skills; registry info in annotations |
| `GET` | `/api/config/features` | New `externalSkills` boolean field |

All other existing skill and agent endpoints are unchanged.

---

## UI Changes

### `rossoctl/ui-v2/src/types/index.ts`

Add to `Skill`:
```typescript
source?: 'local' | 'external';
externalInfo?: {
  registryType: string;
  registryUrl: string;
  registrySkillName: string;
  registrySkillVersion: string;
};
```

### `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx`

In the skill list item: render a small `External` badge (e.g., outlined chip) when `skill.source === 'external'`.

### `rossoctl/ui-v2/src/pages/SkillDetailPage.tsx`

For external skills: replace the `SkillFileTree` component with a "Registry Info" card showing:
- Registry type
- Registry URL (as a link)
- Skill name and version in the registry
- "View in Registry" button if `origin` annotation is set

### `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx`

Add a second tab "From Registry" (shown only when `features.externalSkills` is `true`). Fields:
- Registry type (select: `skillberry` / `generic`)
- Registry URL
- Skill name
- Version (optional, placeholder "latest")
- Display name, description, category (same as local import)

### `rossoctl/ui-v2/src/services/api.ts`

Add `skillService.createExternal(data: CreateExternalSkillRequest)` that calls `POST /skills/external`.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Registry unreachable at pod start | Init container exits non-zero → pod `Init:Error` / `Init:CrashLoopBackOff` |
| Invalid archive format | `tar` exits non-zero → pod fails to start |
| `registryType` has no matching script | Init container tries `<type>.sh`, falls back to `generic.sh` |
| Feature flag disabled, external skill API called | `HTTP 404` (endpoint not registered) |
| External skill ConfigMap missing at agent deploy | Backend returns `HTTP 400` with clear message |

---

## Testing

- **Unit tests** (`rossoctl/backend/tests/test_skills.py`): test `_is_external()`, `_configmap_to_external_skill_info()`, `create_external_skill` endpoint, updated list/detail responses.
- **Unit tests** (`rossoctl/backend/tests/test_agents.py`): test `_ensure_fetcher_scripts_cm()`, `_get_external_skill_init_containers()`, combined local+external `_get_linked_skill_mounts()`.
- **E2E test** (`rossoctl/tests/e2e/`): create external skill reference, create agent referencing it, verify pod starts and `SKILL_FOLDERS` contains the mount path, verify fetcher init container spec is present.
- **Shell script tests**: validate `skillberry.sh` and `generic.sh` exit codes on curl failure, successful extract.

---

## Rollout

1. Feature flag `rossoctl_feature_flag_external_skills` defaults to `False`.
2. Enable flag in dev/staging by setting `ROSSOCTL_FEATURE_FLAG_EXTERNAL_SKILLS=true`.
3. GA: flip default to `True` once E2E tests pass on Kind and HyperShift.
