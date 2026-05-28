# Design: Skillberry Registry Skill Combobox in Import Skill Page

**Date:** 2026-05-28
**Branch:** feat/external-skill-registries
**Scope:** Frontend only — `kagenti/ui-v2/src/pages/ImportSkillPage.tsx`

## Problem

The "From Registry" tab in `ImportSkillPage` has a plain text input for "Skill Name in Registry". Users must know the exact skill name stored in the registry and type it manually. All other fields (Display Name, Description, Version) must also be filled manually.

When using a skillberry-store instance, the full list of available skills is accessible via `GET /skills/`. This design replaces the text input with a filterable combobox that auto-fetches from the registry and auto-fills all dependent fields when a skill is selected.

## Scope

Single file change: `kagenti/ui-v2/src/pages/ImportSkillPage.tsx`.

No backend changes. No new files.

## Behavior

### URL validation

A helper `isValidUrl(url: string): boolean` wraps `new URL(url)` in a try/catch and returns true if no exception is thrown. Used to gate the fetch and the disabled state of the combobox.

### Auto-fetch

A `useEffect` watches `registryUrl` and `registryType`. When both conditions are true — `registryType === 'skillberry'` and `isValidUrl(registryUrl)` — it fires a debounced `fetch` (500 ms delay) to `${registryUrl}/skills/`. The 500 ms debounce prevents a request on every keystroke while the user is still typing the URL.

On success: `registrySkills` is set to the parsed JSON array.
On network/parse error: `registrySkillsError` is set, `registrySkills` is cleared.
When `registryUrl` becomes invalid or empty: `registrySkills` is cleared, error is cleared, combobox resets.

The CORS preflight check confirmed skillberry-store reflects back any requesting origin with credentials, so direct browser fetch works without a backend proxy.

### Skill Name field

Replaced with a PatternFly 5 typeahead combobox using `Select` + `TextInputGroup` inside `MenuToggle`. This is the standard PF5 combobox pattern.

- **Disabled** when `registryUrl` is empty, fails URL validation, or `registrySkillsLoading` is true.
- **Filter:** the user can type inside the combobox to narrow options. `registrySkillNameFilter` holds the current filter string; options are filtered client-side by `skill.name.toLowerCase().includes(filter.toLowerCase())`.
- **Options:** one `SelectOption` per skill. The `value` is `skill.name`; the `description` prop carries `skill.description` as secondary text.
- **Loading state:** while fetching, the `MenuToggle` shows a `Spinner` instead of the caret icon and the combobox is disabled.

### Auto-fill on selection

When a skill is selected from the combobox, the following state values are overwritten:

| State field | Source |
|---|---|
| `registrySkillName` | `skill.name` |
| `registrySkillVersion` | `skill.version` |
| `registryName` | `skill.name` |
| `registryDescription` | `skill.description` |

`registryCategory` is not filled — skillberry skills have a `tags` array, not a category field, so it remains for the user to fill manually.

### Error feedback

- Fetch error: `Alert variant="danger"` rendered inline below the Registry URL field with the message "Could not load skills from registry: {error message}".
- The alert is cleared when the URL changes.

## New state

```typescript
interface SkillberrySkill {
  name: string;
  description: string;
  version: string;
  uuid: string;
}

// Added to component state:
const [registrySkills, setRegistrySkills] = useState<SkillberrySkill[]>([]);
const [registrySkillsLoading, setRegistrySkillsLoading] = useState(false);
const [registrySkillsError, setRegistrySkillsError] = useState<string | null>(null);
const [registrySkillNameOpen, setRegistrySkillNameOpen] = useState(false);
const [registrySkillNameFilter, setRegistrySkillNameFilter] = useState('');
```

## Data flow

```
registryUrl changes
  → isValidUrl? → yes
      → debounce 500ms
      → fetch ${registryUrl}/skills/
      → success → setRegistrySkills([...])
      → error   → setRegistrySkillsError(msg)
  → no
      → setRegistrySkills([])
      → setRegistrySkillsError(null)

user selects skill from combobox
  → setRegistrySkillName(skill.name)
  → setRegistrySkillVersion(skill.version)
  → setRegistryName(skill.name)
  → setRegistryDescription(skill.description)
  → setRegistrySkillNameOpen(false)
  → setRegistrySkillNameFilter('')
```

## Constraints

- Only activates for `registryType === 'skillberry'`. The "generic" registry type keeps the original `TextInput` (no known list endpoint for generic registries).
- No pagination — `GET /skills/` returns all skills; client-side filtering is sufficient for typical registry sizes.
- Skillberry-store's CORS policy allows any requesting origin (verified: it reflects back `Access-Control-Allow-Origin` matching the request origin). Direct browser fetch is safe.

## Testing

Manual test cases:
1. Enter a valid skillberry URL → skills load, combobox enabled, skill names visible.
2. Select a skill → Display Name, Description, Version auto-fill.
3. Enter an invalid URL (e.g. "notaurl") → combobox disabled, no fetch attempted.
4. Clear the URL after a successful load → combobox resets, skills cleared.
5. Enter a URL for an unreachable server → error alert shown below Registry URL field.
6. Type in the combobox filter → list narrows to matching skill names.
7. Switch Registry Type to "generic" → plain TextInput shown, no fetch.
