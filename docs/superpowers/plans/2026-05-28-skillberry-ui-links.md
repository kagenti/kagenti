---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Skillberry UI Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add clickable links to the skillberry-store web UI (port 8002) for external skills in both the Import Skill form and the Skills catalog table.

**Architecture:** Pure frontend. A `getSkillberryUiUrl` helper derives the UI URL from the stored API URL by substituting port 8002. The link appears below the skill name combobox in ImportSkillPage after a skill is selected, and as a Registry column in SkillCatalogPage for skillberry-sourced rows. All commands run from `rossoctl/ui-v2/`.

**Tech Stack:** React 18, PatternFly 5, TypeScript, Vitest

---

## File Map

| File | Change |
|------|--------|
| `rossoctl/ui-v2/src/utils/validation.ts` | Add `getSkillberryUiUrl` helper |
| `rossoctl/ui-v2/src/utils/validation.test.ts` | Add tests for `getSkillberryUiUrl` |
| `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx` | Add link below Skill Name combobox |
| `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx` | Add Registry column with link |

---

### Task 1: `getSkillberryUiUrl` helper + tests

**Files:**
- Modify: `rossoctl/ui-v2/src/utils/validation.ts`
- Modify: `rossoctl/ui-v2/src/utils/validation.test.ts`

- [ ] **Step 1.1: Write the failing tests**

Update the import at the top of `rossoctl/ui-v2/src/utils/validation.test.ts`:

```typescript
import { isValidEnvVarName, isValidContainerImage, isValidImageTag, isValidUrl, getSkillberryUiUrl } from './validation';
```

Append after the `isValidUrl` describe block:

```typescript
describe('getSkillberryUiUrl', () => {
  it('replaces port 8000 with 8002 and appends skill path', () => {
    expect(getSkillberryUiUrl('http://172.26.89.33:8000', 'summarizer'))
      .toBe('http://172.26.89.33:8002/skills/summarizer');
  });

  it('replaces localhost port 8000 with 8002', () => {
    expect(getSkillberryUiUrl('http://localhost:8000', 'my-skill'))
      .toBe('http://localhost:8002/skills/my-skill');
  });

  it('appends port 8002 when no port specified', () => {
    expect(getSkillberryUiUrl('https://skillberry.example.com', 'summarizer'))
      .toBe('https://skillberry.example.com:8002/skills/summarizer');
  });

  it('returns empty string for invalid URL', () => {
    expect(getSkillberryUiUrl('notaurl', 'summarizer')).toBe('');
    expect(getSkillberryUiUrl('', 'summarizer')).toBe('');
  });
});
```

- [ ] **Step 1.2: Run tests — expect FAIL**

```bash
npm run test:unit -- --reporter=verbose 2>&1 | grep -E "getSkillberryUiUrl|FAIL"
```

Expected: `getSkillberryUiUrl is not a function`

- [ ] **Step 1.3: Implement `getSkillberryUiUrl` in `validation.ts`**

Append to `rossoctl/ui-v2/src/utils/validation.ts`:

```typescript
/**
 * Derive the skillberry-store web UI URL from the API URL.
 * Substitutes port 8002 (UI) for the stored API port and appends the skill path.
 * Returns '' if registryUrl is not a valid URL.
 */
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

- [ ] **Step 1.4: Run tests — expect PASS**

```bash
npm run test:unit -- --reporter=verbose 2>&1 | grep -E "getSkillberryUiUrl|✓|×"
```

Expected: all 4 `getSkillberryUiUrl` tests pass, no regressions.

- [ ] **Step 1.5: Commit**

```bash
git add rossoctl/ui-v2/src/utils/validation.ts rossoctl/ui-v2/src/utils/validation.test.ts
git commit -s -m "feat(ui): add getSkillberryUiUrl helper to derive skillberry web UI link"
```

---

### Task 2: Link below Skill Name combobox in ImportSkillPage

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx`

- [ ] **Step 2.1: Add `getSkillberryUiUrl` to the import from `@/utils/validation`**

Find the existing import line:

```typescript
import { isValidUrl } from '@/utils/validation';
```

Replace with:

```typescript
import { isValidUrl, getSkillberryUiUrl } from '@/utils/validation';
```

- [ ] **Step 2.2: Add the link after the Skill Name FormGroup closing tag**

The Skill Name `FormGroup` closes at line ~654 (`</FormGroup>`). Insert the link block immediately after it:

```tsx
                    <FormGroup label="Skill Name in Registry" isRequired fieldId="reg-skill-name">
                      {/* ... existing combobox ... */}
                    </FormGroup>
                    {registryType === 'skillberry' && registrySkillName && getSkillberryUiUrl(registryUrl, registrySkillName) && (
                      <div style={{ marginTop: '0.25rem', fontSize: 'var(--pf-v5-global--FontSize--sm)' }}>
                        <a
                          href={getSkillberryUiUrl(registryUrl, registrySkillName)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View in skillberry-store ↗
                        </a>
                      </div>
                    )}
```

To apply this edit, find the exact closing tag of the Skill Name FormGroup and insert after it. The closing tag currently looks like:

```tsx
                    </FormGroup>
                    <FormGroup label="Version" fieldId="reg-version">
```

Replace with:

```tsx
                    </FormGroup>
                    {registryType === 'skillberry' && registrySkillName && getSkillberryUiUrl(registryUrl, registrySkillName) && (
                      <div style={{ marginTop: '0.25rem', fontSize: 'var(--pf-v5-global--FontSize--sm)' }}>
                        <a
                          href={getSkillberryUiUrl(registryUrl, registrySkillName)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View in skillberry-store ↗
                        </a>
                      </div>
                    )}
                    <FormGroup label="Version" fieldId="reg-version">
```

- [ ] **Step 2.3: Typecheck**

```bash
npm run typecheck 2>&1 | grep -E "error TS|ImportSkillPage"
```

Expected: no errors.

- [ ] **Step 2.4: Commit**

```bash
git add rossoctl/ui-v2/src/pages/ImportSkillPage.tsx
git commit -s -m "feat(ui): add View in skillberry-store link on skill name selection"
```

---

### Task 3: Registry column in SkillCatalogPage

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx`

- [ ] **Step 3.1: Add `getSkillberryUiUrl` import**

Find:

```typescript
import { Skill } from '@/types';
import { skillService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
```

Replace with:

```typescript
import { Skill } from '@/types';
import { skillService } from '@/services/api';
import { NamespaceSelector } from '@/components/NamespaceSelector';
import { getSkillberryUiUrl } from '@/utils/validation';
```

- [ ] **Step 3.2: Add Registry column header**

Find the table header row:

```tsx
              <Tr>
                <Th>Name</Th>
                <Th>Description</Th>
                <Th>Category</Th>
                <Th>Usage Count</Th>
                <Th>Created</Th>
              </Tr>
```

Replace with:

```tsx
              <Tr>
                <Th>Name</Th>
                <Th>Description</Th>
                <Th>Category</Th>
                <Th>Usage Count</Th>
                <Th>Created</Th>
                <Th>Registry</Th>
              </Tr>
```

- [ ] **Step 3.3: Add Registry column cell in each row**

Find the last cell in the row body:

```tsx
                  <Td dataLabel="Created">
                    {skill.createdAt
                      ? new Date(skill.createdAt).toLocaleDateString()
                      : 'N/A'}
                  </Td>
                </Tr>
```

Replace with:

```tsx
                  <Td dataLabel="Created">
                    {skill.createdAt
                      ? new Date(skill.createdAt).toLocaleDateString()
                      : 'N/A'}
                  </Td>
                  <Td dataLabel="Registry">
                    {skill.source === 'external' &&
                    skill.externalInfo?.registryType === 'skillberry' &&
                    getSkillberryUiUrl(skill.externalInfo.registryUrl, skill.externalInfo.registrySkillName) ? (
                      <a
                        href={getSkillberryUiUrl(skill.externalInfo.registryUrl, skill.externalInfo.registrySkillName)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                      >
                        View ↗
                      </a>
                    ) : (
                      <span>—</span>
                    )}
                  </Td>
                </Tr>
```

- [ ] **Step 3.4: Typecheck**

```bash
npm run typecheck 2>&1 | grep -E "error TS|SkillCatalogPage"
```

Expected: no errors.

- [ ] **Step 3.5: Lint**

```bash
npm run lint 2>&1 | grep -E "SkillCatalogPage|ImportSkillPage" | head -10
```

Expected: no new errors in either file.

- [ ] **Step 3.6: Commit**

```bash
git add rossoctl/ui-v2/src/pages/SkillCatalogPage.tsx
git commit -s -m "$(cat <<'EOF'
feat(ui): add Registry column with skillberry UI link to skills catalog table

- External skillberry skills show a "View ↗" link in the Registry column
- Link derived by replacing API port (8000) with UI port (8002)
- onClick stops row-navigation propagation so the link opens correctly
- Non-external and non-skillberry rows show —

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>
EOF
)"
```
