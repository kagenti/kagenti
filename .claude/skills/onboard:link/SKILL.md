---
name: onboard:link
description: Clone target repo into .repos/ and verify skill discovery works
---

# Onboard: Link to Hub

Clone an orchestrated repository into the kagenti hub's `.repos/` directory
and verify that Claude Code can discover the target's skills.

## Steps

### 1. Clone the repository

```bash
git clone git@github.com:org/repo.git .repos/<repo-name>
```

If already cloned, pull latest:

```bash
git -C .repos/<repo-name> pull --ff-only
```

### 2. Verify .claude/skills/ exists

```bash
ls .repos/<repo-name>/.claude/skills/
```

```bash
ls .repos/<repo-name>/CLAUDE.md
```

If either is missing, run `orchestrate` on the target first.

### 3. Verify skill discovery

```bash
find .repos/<repo-name>/.claude/skills/ -name SKILL.md
```

Claude Code discovers skills from nested `.claude/skills/` directories
on-demand when reading files in subdirectories.

### 4. Update inventory

Add entry to `.repos/README.md`:

```markdown
# Onboarded Repositories

| Repo | Status | Last Orchestrated |
|------|--------|-------------------|
| kagenti-operator | Orchestrated | 2026-02-14 |
```

Status values: `Orchestrated`, `Linked`, `Onboarded`

### 5. Commit the link

```bash
git add .repos/README.md
```

```bash
git commit -s -m "feat: onboard <repo-name> into hub inventory"
```

The cloned repo itself is NOT committed (`.repos/` is in `.gitignore`).

## Related Skills

- `onboard` — Router skill
- `onboard:standards` — Apply kagenti conventions (next step)
- `orchestrate:scan` — Create CLAUDE.md if missing
