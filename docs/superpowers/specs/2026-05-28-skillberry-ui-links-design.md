---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Design: Skillberry UI Links for External Skills

**Date:** 2026-05-28
**Branch:** feat/external-skill-registries
**Scope:** Frontend only — `validation.ts`, `ImportSkillPage.tsx`, `SkillCatalogPage.tsx`

## Problem

When a skill is sourced from a skillberry-store registry, users have no way to navigate directly to the skillberry-store UI to inspect that skill. The stored `registryUrl` is the API URL (port 8000); the skillberry-store web UI is always on port 8002 at the same host.

## URL Derivation

The skillberry UI URL is derived from the API URL by replacing the port with 8002 and appending the skill name path:

```
http://172.26.89.33:8000  +  summarizer
→ http://172.26.89.33:8002/skills/summarizer
```

This is always Option A: port substitution only, no user-configurable override. If the port is absent (e.g. `http://skillberry.example.com`), `new URL().port` is `''` and setting it to `8002` produces `http://skillberry.example.com:8002/skills/summarizer`.

Returns `''` on malformed input; callers guard with a truthiness check.

## New Helper

**File:** `rossoctl/ui-v2/src/utils/validation.ts`

```typescript
export const getSkillberryUiUrl = (registryUrl: string, skillName: string): string => {
  try {
    const url = new URL(registryUrl);
    url.port = '8002';
    return `${url.origin}/skills/${skillName}`;
  } catch {
    return '';
  }
};
```

**Tests:** `rossoctl/ui-v2/src/utils/validation.test.ts`

- Port 8000 → 8002 with skill name in path
- No port in URL → port 8002 appended
- Empty registryUrl → returns `''`
- Empty skillName → returns URL with empty skill segment (acceptable)

## ImportSkillPage

**File:** `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx`

After the Skill Name `FormGroup` (below the combobox), add a conditional link:

```
Condition: registryType === 'skillberry' && registrySkillName is non-empty
           && getSkillberryUiUrl(registryUrl, registrySkillName) is non-empty
Renders:   <a href={...} target="_blank" rel="noreferrer">View in skillberry-store ↗</a>
Style:     small text, marginTop 0.25rem
```

This gives the user immediate confirmation that the selected skill is reachable and lets them verify the content before registering.

## SkillCatalogPage

**File:** `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx`

Add a **Registry** column as the rightmost column in the skills table.

- **External + skillberry:** render `<a href={getSkillberryUiUrl(...)} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>View ↗</a>`
- **All other rows:** render `—`

`e.stopPropagation()` is required because the `<Tr>` has an `onClick` that navigates to the skill detail page — without stopping propagation, clicking the link also triggers the row navigation.

Data available on `Skill`:
- `skill.source` — `'external'` for registry skills
- `skill.externalInfo.registryType` — `'skillberry'` for skillberry skills
- `skill.externalInfo.registryUrl` — the API URL
- `skill.externalInfo.registrySkillName` — the skill name in the registry

## Files Changed

| File | Change |
|------|--------|
| `rossoctl/ui-v2/src/utils/validation.ts` | Add `getSkillberryUiUrl` |
| `rossoctl/ui-v2/src/utils/validation.test.ts` | Add tests for `getSkillberryUiUrl` |
| `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx` | Add link below skill name combobox |
| `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx` | Add Registry column with link |

No backend changes. No new component files.
