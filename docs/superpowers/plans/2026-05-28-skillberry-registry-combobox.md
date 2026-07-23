---
draft: true       # excluded from https://www.rossoctl.dev/
---

# Skillberry Registry Combobox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the plain text input for "Skill Name in Registry" in the From Registry tab with a filterable combobox that auto-fetches available skills from the skillberry-store API when a valid URL is entered, and auto-fills all form fields when a skill is selected.

**Architecture:** Pure frontend change — no backend involved. The browser fetches `GET {registryUrl}/skills/` directly from the skillberry-store (CORS verified). A `useEffect` debounces the fetch on `registryUrl`/`registryType` changes. The PF5 typeahead combobox pattern uses `Select` + `MenuToggle variant="typeahead"` + `TextInputGroup` inside the toggle.

**Tech Stack:** React 18, PatternFly 5 (`@patternfly/react-core`), Vitest (unit tests), TypeScript

---

## File Map

| File | Change |
|------|--------|
| `rossoctl/ui-v2/src/utils/validation.ts` | Add `isValidUrl` helper |
| `rossoctl/ui-v2/src/utils/validation.test.ts` | Add tests for `isValidUrl` |
| `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx` | New state, useEffect, combobox, auto-fill, error Alert |

All changes are in the `rossoctl/ui-v2/` directory. Run all commands from there.

---

### Task 1: `isValidUrl` utility

**Files:**
- Modify: `rossoctl/ui-v2/src/utils/validation.ts`
- Modify: `rossoctl/ui-v2/src/utils/validation.test.ts`

- [ ] **Step 1.1: Write the failing tests**

Append to `rossoctl/ui-v2/src/utils/validation.test.ts`:

```typescript
describe('isValidUrl', () => {
  it('accepts http URLs', () => {
    expect(isValidUrl('http://localhost:8000')).toBe(true);
    expect(isValidUrl('http://172.26.89.33:8000')).toBe(true);
    expect(isValidUrl('http://host.docker.internal:8000')).toBe(true);
  });

  it('accepts https URLs', () => {
    expect(isValidUrl('https://skillberry.example.com')).toBe(true);
  });

  it('rejects empty string', () => {
    expect(isValidUrl('')).toBe(false);
  });

  it('rejects plain text without protocol', () => {
    expect(isValidUrl('notaurl')).toBe(false);
    expect(isValidUrl('localhost:8000')).toBe(false);
  });

  it('rejects partial URLs', () => {
    expect(isValidUrl('http://')).toBe(false);
  });
});
```

Update the import at the top of the test file to include `isValidUrl`:

```typescript
import { isValidEnvVarName, isValidContainerImage, isValidImageTag, isValidUrl } from './validation';
```

- [ ] **Step 1.2: Run tests — expect FAIL**

```bash
npm run test:unit -- --reporter=verbose 2>&1 | grep -E "FAIL|isValidUrl|Cannot find"
```

Expected: error like `isValidUrl is not a function` or similar import failure.

- [ ] **Step 1.3: Implement `isValidUrl` in `validation.ts`**

Append to `rossoctl/ui-v2/src/utils/validation.ts`:

```typescript
/**
 * Return true if url is a syntactically valid absolute URL.
 * Requires a protocol (http/https). Used to gate skillberry registry fetches.
 */
export const isValidUrl = (url: string): boolean => {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
};
```

- [ ] **Step 1.4: Run tests — expect PASS**

```bash
npm run test:unit -- --reporter=verbose 2>&1 | grep -E "PASS|FAIL|isValidUrl"
```

Expected: all `isValidUrl` tests pass, no regressions.

- [ ] **Step 1.5: Commit**

```bash
git add rossoctl/ui-v2/src/utils/validation.ts rossoctl/ui-v2/src/utils/validation.test.ts
git commit -s -m "feat(ui): add isValidUrl helper to validation utilities"
```

---

### Task 2: State, type, auto-fetch effect, and error Alert in ImportSkillPage

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx`

- [ ] **Step 2.1: Add `SkillberrySkill` interface and new state**

After the existing `interface AdditionalFile` block (around line 46), add:

```typescript
interface SkillberrySkill {
  name: string;
  description: string;
  version: string;
  uuid: string;
}
```

After the existing registry state declarations (after line 77, `const [registryCategory, setRegistryCategory] = React.useState('');`), add:

```typescript
const [registrySkills, setRegistrySkills] = useState<SkillberrySkill[]>([]);
const [registrySkillsLoading, setRegistrySkillsLoading] = useState(false);
const [registrySkillsError, setRegistrySkillsError] = useState<string | null>(null);
const [registrySkillNameOpen, setRegistrySkillNameOpen] = useState(false);
const [registrySkillNameFilter, setRegistrySkillNameFilter] = useState('');
```

- [ ] **Step 2.2: Add `isValidUrl` import**

Update the import from `@/utils/githubSkillImporter`:

```typescript
import { importSkillFromGitHub, isValidGitHubUrl } from '@/utils/githubSkillImporter';
import { isValidUrl } from '@/utils/validation';
```

- [ ] **Step 2.3: Add the auto-fetch `useEffect`**

After the existing GitHub import `useEffect` block (after the `}, [url]);` closing), add:

```typescript
useEffect(() => {
  if (registryType !== 'skillberry' || !isValidUrl(registryUrl)) {
    setRegistrySkills([]);
    setRegistrySkillsError(null);
    setRegistrySkillNameFilter('');
    setRegistrySkillName('');
    return;
  }

  setRegistrySkillsLoading(true);
  setRegistrySkillsError(null);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    fetch(`${registryUrl}/skills/`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((skills: SkillberrySkill[]) => {
        setRegistrySkills(skills);
        setRegistrySkillsLoading(false);
      })
      .catch((err) => {
        if (err.name === 'AbortError') return;
        setRegistrySkillsError(err.message || 'Failed to load skills from registry');
        setRegistrySkills([]);
        setRegistrySkillsLoading(false);
      });
  }, 500);

  return () => {
    clearTimeout(timeoutId);
    controller.abort();
  };
}, [registryUrl, registryType]);
```

- [ ] **Step 2.4: Add fetch error Alert below the Registry URL FormGroup**

Find the Registry URL `FormGroup` closing tag (after the `TextInput` for `reg-url`):

```tsx
<FormGroup label="Registry URL" isRequired fieldId="reg-url">
  <TextInput
    id="reg-url"
    value={registryUrl}
    onChange={(_e, v) => setRegistryUrl(v)}
    placeholder="https://skillberry.example.com"
  />
</FormGroup>
```

Replace it with:

```tsx
<FormGroup label="Registry URL" isRequired fieldId="reg-url">
  <TextInput
    id="reg-url"
    value={registryUrl}
    onChange={(_e, v) => setRegistryUrl(v)}
    placeholder="http://host.docker.internal:8000"
  />
  {registrySkillsError && (
    <Alert
      variant="danger"
      title="Could not load skills from registry"
      isInline
      isPlain
      style={{ marginTop: '0.5rem' }}
    >
      {registrySkillsError}
    </Alert>
  )}
</FormGroup>
```

- [ ] **Step 2.5: Typecheck**

```bash
npm run typecheck 2>&1 | grep -E "error TS|ImportSkillPage"
```

Expected: no errors. Fix any type errors before continuing.

- [ ] **Step 2.6: Commit**

```bash
git add rossoctl/ui-v2/src/pages/ImportSkillPage.tsx
git commit -s -m "feat(ui): add skillberry skill list auto-fetch to ImportSkillPage"
```

---

### Task 3: Replace TextInput with filterable combobox and wire auto-fill

**Files:**
- Modify: `rossoctl/ui-v2/src/pages/ImportSkillPage.tsx`

- [ ] **Step 3.1: Add new PF and icon imports**

Update the `@patternfly/react-core` import block to add `TextInputGroup`, `TextInputGroupMain`, `TextInputGroupUtilities`:

```typescript
import {
  PageSection,
  Title,
  Text,
  TextContent,
  Card,
  CardTitle,
  CardBody,
  Form,
  FormGroup,
  TextInput,
  TextInputGroup,
  TextInputGroupMain,
  TextInputGroupUtilities,
  TextArea,
  Button,
  Alert,
  ActionGroup,
  HelperText,
  HelperTextItem,
  Split,
  SplitItem,
  List,
  ListItem,
  Label,
  Spinner,
  Tabs,
  Tab,
  TabTitleText,
  Select,
  SelectList,
  SelectOption,
  MenuToggle,
} from '@patternfly/react-core';
```

Update the `@patternfly/react-icons` import to add `TimesCircleIcon`:

```typescript
import { PlusCircleIcon, TrashIcon, GithubIcon, TimesCircleIcon } from '@patternfly/react-icons';
```

- [ ] **Step 3.2: Add `isSkillNameDisabled` computed variable**

Directly before the `return (` statement, add:

```typescript
const isSkillNameDisabled =
  registryType !== 'skillberry' || !isValidUrl(registryUrl) || registrySkillsLoading;
```

- [ ] **Step 3.3: Replace the Skill Name TextInput with the combobox**

Find and replace the current "Skill Name in Registry" `FormGroup`:

```tsx
<FormGroup label="Skill Name in Registry" isRequired fieldId="reg-skill-name">
  <TextInput
    id="reg-skill-name"
    value={registrySkillName}
    onChange={(_e, v) => setRegistrySkillName(v)}
    placeholder="code-review"
  />
</FormGroup>
```

Replace with:

```tsx
<FormGroup label="Skill Name in Registry" isRequired fieldId="reg-skill-name">
  <Select
    isOpen={registrySkillNameOpen}
    onOpenChange={(isOpen) => setRegistrySkillNameOpen(isOpen)}
    onSelect={(_e, val) => {
      const skill = registrySkills.find((s) => s.name === val);
      if (skill) {
        setRegistrySkillName(skill.name);
        setRegistrySkillNameFilter(skill.name);
        setRegistrySkillVersion(skill.version);
        setRegistryName(skill.name);
        setRegistryDescription(skill.description);
      }
      setRegistrySkillNameOpen(false);
    }}
    toggle={(ref) => (
      <MenuToggle
        ref={ref}
        variant="typeahead"
        onClick={() => {
          if (!isSkillNameDisabled) setRegistrySkillNameOpen(!registrySkillNameOpen);
        }}
        isExpanded={registrySkillNameOpen}
        isDisabled={isSkillNameDisabled}
        style={{ width: '100%' }}
      >
        {registrySkillsLoading ? (
          <Split hasGutter>
            <SplitItem><Spinner size="sm" /></SplitItem>
            <SplitItem>Loading skills...</SplitItem>
          </Split>
        ) : (
          <TextInputGroup isPlain>
            <TextInputGroupMain
              value={registrySkillNameFilter}
              onClick={() => setRegistrySkillNameOpen(true)}
              onChange={(_e, val) => {
                setRegistrySkillNameFilter(val);
                if (val !== registrySkillName) setRegistrySkillName('');
                if (!registrySkillNameOpen) setRegistrySkillNameOpen(true);
              }}
              autoComplete="off"
              placeholder={isSkillNameDisabled ? 'Enter a valid Registry URL first' : 'Select or type a skill name'}
            />
            {registrySkillNameFilter && (
              <TextInputGroupUtilities>
                <Button
                  variant="plain"
                  onClick={() => {
                    setRegistrySkillNameFilter('');
                    setRegistrySkillName('');
                    setRegistrySkillVersion('');
                    setRegistryName('');
                    setRegistryDescription('');
                  }}
                  aria-label="Clear skill selection"
                >
                  <TimesCircleIcon />
                </Button>
              </TextInputGroupUtilities>
            )}
          </TextInputGroup>
        )}
      </MenuToggle>
    )}
  >
    <SelectList>
      {registrySkills
        .filter(
          (s) =>
            !registrySkillNameFilter ||
            s.name.toLowerCase().includes(registrySkillNameFilter.toLowerCase())
        )
        .map((s) => (
          <SelectOption key={s.uuid} value={s.name} description={s.description}>
            {s.name}
          </SelectOption>
        ))}
      {!registrySkillsLoading && registrySkills.length === 0 && !registrySkillsError && isValidUrl(registryUrl) && (
        <SelectOption isDisabled value="">
          No skills found in registry
        </SelectOption>
      )}
    </SelectList>
  </Select>
</FormGroup>
```

- [ ] **Step 3.4: Update the Register button's `isDisabled` condition**

The current condition is:
```tsx
isDisabled={
  !registryName || !registryUrl || !registrySkillName || registryMutation.isPending
}
```

This is correct — `registrySkillName` is set when a skill is selected from the combobox. No change needed.

- [ ] **Step 3.5: Typecheck**

```bash
npm run typecheck 2>&1 | grep -E "error TS|ImportSkillPage"
```

Expected: no errors. Common fixes if needed:
- `SelectOption isDisabled` may need `key` prop — add `key="empty"`.
- `MenuToggle ref` type: `ref` is passed by PF internally via the `toggle` callback, no explicit typing needed.

- [ ] **Step 3.6: Lint**

```bash
npm run lint 2>&1 | grep -E "ImportSkillPage|error|warning" | head -20
```

Expected: no new errors. Fix any unused variable warnings.

- [ ] **Step 3.7: Commit**

```bash
git add rossoctl/ui-v2/src/pages/ImportSkillPage.tsx
git commit -s -m "feat(ui): replace skill name text input with filterable combobox in From Registry tab

- Auto-fetch GET /skills/ from skillberry-store when registry URL is valid
- Skill Name field becomes a typeahead combobox filtered by typed text
- Selecting a skill auto-fills Version, Display Name, and Description
- Combobox disabled when URL is invalid/empty or skills are loading
- Clear button resets all auto-filled fields
- Fetch error shown inline below Registry URL field

Assisted-By: Claude (Anthropic AI) <noreply@anthropic.com>"
```

---

## Manual Test Checklist

After all tasks are committed, verify these scenarios with the running UI (`http://rossoctl-ui.localtest.me:8080`):

1. Open **Skills → Import Skill → From Registry** tab
2. With skillberry-store running at `http://localhost:8000`:
   - [ ] Enter `http://localhost:8000` in Registry URL → spinner appears briefly → combobox becomes enabled → dropdown shows skill names
   - [ ] Type "sum" in the combobox → list filters to skills containing "sum"
   - [ ] Select "summarizer" → Version, Display Name, Description auto-fill
   - [ ] Click the × clear button → all auto-filled fields reset to empty
3. Enter an invalid URL (e.g. `notaurl`) → combobox shows "Enter a valid Registry URL first", is disabled
4. Clear the URL after a successful load → combobox resets, no stale skills shown
5. Enter URL of an unreachable server (e.g. `http://localhost:9999`) → red Alert appears below Registry URL field
6. Switch Registry Type to "generic" → combobox is disabled (not skillberry)
7. With valid URL + skill selected → click "Register External Skill" → navigates to skill catalog, new external skill visible with External badge
