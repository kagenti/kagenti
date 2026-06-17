# Skill Auto-Sync Design

**Date:** 2026-06-17
**Feature gate:** `kagenti_feature_flag_external_skills`
**Approach:** Backend async loop + Kubernetes ConfigMap state (Approach A)

---

## Overview

Auto-sync keeps the Kagenti skill catalog synchronized with a remote Skillberry registry automatically. When enabled, the backend polls the registry every N seconds, computes a diff against the current Kagenti skills, and applies creates, version-updates, and deletes — no user action required after initial setup.

Auto-sync is **cluster-wide**: one registry configuration applies to all namespaces. Skill distribution across namespaces is governed by `namespace:` tags on skills in the Skillberry store.

The feature is entirely gated behind the existing `kagenti_feature_flag_external_skills` flag. No new feature flag is introduced.

---

## Namespace Mapping

Skillberry uses `namespace:` tag prefixes (e.g. `namespace:default`, `namespace:team1`) to scope skills. Kagenti maps these to its own enabled namespaces:

| Skillberry tag(s) on a skill | Synced to Kagenti namespace(s) |
|---|---|
| `namespace:default` | All enabled Kagenti namespaces |
| `namespace:team1` | `team1` only (if it is an enabled Kagenti namespace) |
| `namespace:default` + `namespace:team1` | All namespaces (`default` covers everything) |
| No `namespace:` tag at all | Treated as `namespace:default` — synced to all namespaces |

---

## Component Map

```
┌─────────────────────────────────────────────────────────────┐
│  Skillberry-Store                                            │
│  GET /skills/  →  [{name, version, uuid, tags:[...], ...}]  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP polling every N seconds
┌──────────────────────────▼──────────────────────────────────┐
│  Kagenti Backend                                             │
│                                                              │
│  services/skill_autosync.py  ← new background loop          │
│    └─ reads  kagenti-system/kagenti-skill-autosync-config    │
│    └─ lists  skills in each enabled namespace                │
│    └─ computes diff, creates/patches/deletes ConfigMaps      │
│                                                              │
│  routers/skills.py  ← 3 new endpoints                       │
│    GET    /api/v1/skills/autosync                            │
│    POST   /api/v1/skills/autosync                            │
│    DELETE /api/v1/skills/autosync                            │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST
┌──────────────────────────▼──────────────────────────────────┐
│  Kagenti UI                                                  │
│                                                              │
│  ImportSkillPage (From Registry tab)                         │
│    └─ Auto-Sync control panel at top of tab                  │
│    └─ rest of tab hidden when auto-sync active               │
│    └─ Upload Files tab shows disabled notice                 │
│                                                              │
│  SkillCatalogPage                                            │
│    └─ banner when auto-sync active                           │
│    └─ "Import Skill" → "Manage in Skillberry ↗"             │
│    └─ "Auto-synced" badge on auto-synced skills              │
└─────────────────────────────────────────────────────────────┘
```

---

## Backend Changes

### `config.py`

One new setting:

```python
skill_autosync_interval: int = 30  # seconds between registry sync checks (env: SKILL_AUTOSYNC_INTERVAL)
```

This is the backend default. The active interval is also stored in the auto-sync ConfigMap (set by the user when enabling), so the ConfigMap value takes precedence at runtime.

### `constants.py`

Four new constants added in the "External skill registry constants" block:

```python
SKILL_AUTOSYNC_CONFIG_CM = "kagenti-skill-autosync-config"  # ConfigMap in kagenti-system
SKILL_AUTOSYNC_LABEL     = "kagenti.io/auto-sync"           # "true" on auto-synced skills
SKILL_NS_TAG_PREFIX      = "namespace:"                      # skillberry namespace tag prefix
SKILL_NS_DEFAULT_TAG     = "namespace:default"               # skillberry "sync to all" tag
```

### Auto-Sync State: Kubernetes ConfigMap

A single ConfigMap in `kagenti-system` holds the cluster-wide config. The background loop reads it on every iteration — no in-memory state needed, so the loop is stateless and resilient to backend restarts.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kagenti-skill-autosync-config
  namespace: kagenti-system
  labels:
    kagenti.io/type: skill-autosync
data:
  enabled:        "true"
  registry-type:  "skillberry"
  registry-url:   "http://skillberry.example.com:8000"
  sync-interval:  "30"
  last-synced-at: "2026-06-17T10:00:00Z"   # updated after each successful pass
  skill-count:    "12"                       # updated after each successful pass
```

`last-synced-at` and `skill-count` are patched by the loop after each successful sync so the UI can display them without a separate query.

### Auto-Synced Skill Marker

Every skill ConfigMap created by the loop gets one extra label on top of the standard external-skill labels:

```
kagenti.io/auto-sync: "true"
```

Existing labels/annotations (`kagenti.io/source=external`, `kagenti.io/registry-url`, `kagenti.io/registry-skill-name`, `kagenti.io/registry-skill-version`) are unchanged and sufficient. The `auto-sync` label enables fast bulk-listing and bulk-deletion.

### New Service: `services/skill_autosync.py`

Follows the identical structure of `services/reconciliation.py`.

**Public API:**

| Function | Purpose |
|---|---|
| `run_skill_autosync_loop()` | Entry point for `asyncio.create_task()` in `main.py` |
| `sync_skills_once(kube)` | Single sync pass (also usable from tests or a future "sync now" endpoint) |

**Internal functions:**

| Function | Purpose |
|---|---|
| `_get_autosync_config(kube)` | Reads ConfigMap from `kagenti-system`; returns dict or `None` |
| `_update_sync_status(kube, count, ts)` | Patches `last-synced-at` and `skill-count` into ConfigMap |
| `_fetch_registry_skills(registry_url)` | `GET {url}/skills/` → list of Skillberry skills |
| `_namespace_distribution(registry_skills, kagenti_namespaces)` | Returns `dict[namespace → list[skill]]` using tag mapping rules |
| `_get_autosync_skills(kube, namespace)` | Lists ConfigMaps labelled `kagenti.io/auto-sync=true` in a namespace |
| `_apply_diff(kube, namespace, target_skills, local_skills, registry_url, registry_type)` | Computes and applies creates, version-patches, and deletes |

**Loop structure:**

```python
async def run_skill_autosync_loop() -> None:
    await asyncio.sleep(settings.skill_autosync_interval)   # initial delay — let cluster settle
    while True:
        interval = settings.skill_autosync_interval  # fallback if ConfigMap absent
        try:
            kube = get_kubernetes_service()
            interval = await sync_skills_once(kube)  # returns effective interval from ConfigMap
        except Exception:
            logger.exception("Skill auto-sync error")
        await asyncio.sleep(interval)
```

`sync_skills_once` reads `sync-interval` from the ConfigMap and returns it as the effective sleep duration, so interval changes take effect on the next cycle without a backend restart. If auto-sync is not configured (ConfigMap absent), `sync_skills_once` returns `settings.skill_autosync_interval` as a no-op pass.

**Diff logic in `_apply_diff`:**

Skills are matched by `kagenti.io/registry-skill-name` annotation (the Skillberry skill `name` field).

| Condition | Action |
|---|---|
| In registry, not in Kagenti | Create external skill reference ConfigMap |
| In Kagenti, not in registry | Delete ConfigMap |
| In both, version changed | Patch `kagenti.io/registry-skill-version` annotation only |
| In both, same version | No-op |

Version-only patching (not delete+create) is correct because the runtime fetcher (`alpine` init container) always fetches from `{registryUrl}/skills/{name}/export-anthropic` at agent start, so it gets the current content regardless of what version string is stored in Kagenti.

The loop calls internal helper functions from `routers/skills.py` directly (not via HTTP), following the same pattern as `reconciliation.py` calling `finalize_shipwright_build`.

### New API Endpoints in `routers/skills.py`

All three routes are gated by `kagenti_feature_flag_external_skills`.

**`GET /api/v1/skills/autosync`**

Returns current status. No auth required (same as `GET /api/v1/config/features`).

Response when active:
```json
{
  "enabled": true,
  "registryType": "skillberry",
  "registryUrl": "http://...",
  "syncInterval": 30,
  "lastSyncedAt": "2026-06-17T10:00:00Z",
  "skillCount": 12
}
```

Response when inactive:
```json
{ "enabled": false }
```

**`POST /api/v1/skills/autosync`**

Enables auto-sync.

Request body:
```json
{
  "registryType": "skillberry",
  "registryUrl": "http://...",
  "syncInterval": 30
}
```

Pre-condition: scans all enabled namespaces for any existing skills (auto-synced or manually imported). If any exist, returns **HTTP 409** with `"detail": "Remove all existing skills before enabling auto-sync"`.

On success: creates `kagenti-skill-autosync-config` in `kagenti-system` and returns the same shape as GET.

**`DELETE /api/v1/skills/autosync`**

Disables auto-sync:
1. Deletes all ConfigMaps labelled `kagenti.io/auto-sync=true` across all enabled namespaces
2. Deletes `kagenti-skill-autosync-config` from `kagenti-system`
3. Returns **HTTP 204**

### `main.py` — Start the Loop

Inside the existing `external_skills` feature-flag conditional block:

```python
if settings.kagenti_feature_flag_external_skills:
    # ... existing module load ...
    from app.services.skill_autosync import run_skill_autosync_loop
    skill_autosync_task = asyncio.create_task(run_skill_autosync_loop())
    logger.info(
        "Skill auto-sync started (default interval: %ds)",
        settings.skill_autosync_interval,
    )
```

Cancellation in lifespan shutdown follows the identical reconciliation pattern.

---

## Frontend Changes

### `types/index.ts`

```typescript
interface SkillAutoSyncConfig {
  registryType: string
  registryUrl:  string
  syncInterval: number
}

interface SkillAutoSyncStatus {
  enabled:       boolean
  registryType?: string
  registryUrl?:  string
  syncInterval?: number
  lastSyncedAt?: string
  skillCount?:   number
}
```

### `services/api.ts`

Three new methods added to `skillService`:

```typescript
getAutoSync():                             Promise<SkillAutoSyncStatus>
enableAutoSync(cfg: SkillAutoSyncConfig):  Promise<SkillAutoSyncStatus>
disableAutoSync():                         Promise<void>
```

### `ImportSkillPage.tsx` — "From Registry" tab

Auto-sync status is fetched with `useQuery` on mount, polling every 10 seconds while the page is open so `lastSyncedAt` and `skillCount` stay current.

**Auto-sync panel at the top of the "From Registry" tab:**

When auto-sync is **disabled**:

```
┌─ Auto-Sync ──────────────────────────────────────────────────┐
│  Automatically keep Kagenti skills in sync with a remote     │
│  registry. Skills are added, updated, and removed as the     │
│  registry changes.                                           │
│                                                              │
│  Registry Type  [skillberry ▼]                               │
│  Registry URL   [________________________________]           │
│  Sync Interval  [30] seconds                                 │
│                                                              │
│  [Enable Auto-Sync]                                          │
└──────────────────────────────────────────────────────────────┘
── existing manual import form fields below ──
```

The "existing skills" warning is shown only after the backend returns HTTP 409 — not pre-fetched on page load.

When auto-sync is **enabled** (existing manual form fields are not rendered):

```
┌─ Auto-Sync Active ────────────────────────────────────────────┐
│  ✓ Syncing every 30s from:                                    │
│    http://skillberry.example.com:8000                         │
│                                                               │
│  12 skills synced  •  Last synced: 2 minutes ago              │
│                                                               │
│  [Manage skills in Skillberry Store ↗]  [Disable Auto-Sync]  │
└───────────────────────────────────────────────────────────────┘
```

"Manage skills in Skillberry Store ↗" uses the existing `getSkillberryUiUrl()` utility and opens in a new tab.

"Disable Auto-Sync" shows a PatternFly confirmation modal first:
> "This will remove all 12 auto-synced skills. Continue?"

On confirm: calls `DELETE /api/v1/skills/autosync`, then navigates to `/skills`.

**"Upload Files" tab when auto-sync is active:**

An inline `Alert` with `variant="info"` at the top of the tab:

```
ℹ Auto-sync is active. Manual skill import is disabled.
  Disable auto-sync to import skills manually.
```

The "Import Skill" submit button is disabled while this notice is present.

### `SkillCatalogPage.tsx`

Auto-sync status is fetched with `useQuery` on mount (single fetch, no polling needed).

When `autoSyncStatus.enabled` is true:

1. **Page banner** — inline `Alert` with `variant="info"` at the top:
   ```
   🔄  Auto-sync active — syncing from http://skillberry.example.com:8000
       [Manage in Skillberry Store ↗]
   ```

2. **"Import Skill" button** changes label to `"Manage in Skillberry Store ↗"` and opens the skillberry-store UI in a new tab instead of navigating to `/skills/import`.

3. **"Auto-synced" badge** — a PatternFly `Label` with `color="blue"` and text `"Auto-synced"` is shown next to the skill name in the list when `skill.labels["kagenti.io/auto-sync"] === "true"`.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Skillberry registry unreachable during sync loop | Log warning, skip this cycle, try again next interval |
| Kagenti namespace unreachable during sync | Log warning, skip that namespace, continue with others |
| ConfigMap write fails during skill create/delete | Log error, skip that skill, continue with rest of diff |
| Backend 409 on enable (existing skills) | UI shows warning: "Remove all existing skills before enabling auto-sync" |
| Backend unreachable from UI | UI shows error inline using existing PatternFly `Alert` pattern |

Errors never terminate the loop — they are logged and the loop sleeps normally before the next attempt.

---

## Files Changed

### New files
- `kagenti/backend/app/services/skill_autosync.py`

### Modified files
- `kagenti/backend/app/core/config.py` — add `skill_autosync_interval`
- `kagenti/backend/app/core/constants.py` — add 4 new constants
- `kagenti/backend/app/routers/skills.py` — add 3 new endpoints + Pydantic models
- `kagenti/backend/app/main.py` — start auto-sync loop in lifespan
- `kagenti/ui-v2/src/types/index.ts` — add `SkillAutoSyncConfig`, `SkillAutoSyncStatus`
- `kagenti/ui-v2/src/services/api.ts` — add 3 new `skillService` methods
- `kagenti/ui-v2/src/pages/ImportSkillPage.tsx` — add auto-sync panel to "From Registry" tab
- `kagenti/ui-v2/src/pages/SkillCatalogPage.tsx` — add banner, badge, button change
