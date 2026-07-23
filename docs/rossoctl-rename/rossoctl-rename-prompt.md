# Rossoctl Rename — Claude Code Execution Prompt

**You are Claude Code, executing the Kagenti → Rossoctl rename for one repository at a time.**

Your companion document is **`rossoctl-rename-playbook.md`** (same folder). It is the source of truth for every naming decision, the scope, the string map, the verification gate, and the PR conventions. **Read it fully before you do anything.** This prompt tells you *how to operate*; the playbook tells you *what's correct*.

Your job is the mechanical, per-repo content rename and its PR. Your job is **not** to run the GitHub org/repo rename, the cluster migrations, or the external/community rebrand — those are human- and owner-driven (playbook §5.3, §5.4, §7, §12).

---

## Operating mode: plan first, then execute

Work in two clearly separated stages. **Do not modify any file until a human has approved your plan.** If you have plan mode available, use it for Stage 1.

1. **Stage 1 — Plan.** Investigate the target repo and produce the written plan described below. Then **stop and ask for confirmation.**
2. **Stage 2 — Execute.** Only after a human explicitly approves, carry out the plan. Pause again at each runtime-contract item (see guardrails) for a second, explicit sign-off before touching it.

One repo per run. The human tells you which repo. Follow the dependency order in playbook §3 across runs.

---

## Hard guardrails (never violate these)

1. **Never touch private or archived repos.** This effort is for **public, active** repos only. As your very first action, confirm the target with:
   ```
   gh repo view <owner>/<repo> --json isPrivate,isArchived,visibility
   ```
   If it is private or archived, **STOP immediately** and report that it's out of scope (playbook §3/§4). Do not clone, edit, or open anything.
2. **Never blind-replace a runtime contract.** The bold rows in playbook §2 — CRD groups (`*.kagenti.dev`, `mcp.kagenti.com`, `*.kagenti.io`), label/annotation domains (`kagenti.io/*`, `protocol.kagenti.io/*`), namespaces (`kagenti-system`, `kagenti-webhook-system`, `kagenti-traces`), the Keycloak realm (`kagenti`), and the SPIFFE trust domain (`kagenti.local`, `kagenti.example.com`) — are cluster/identity contracts. **List them, never auto-edit them.** They change only under the migration owners' direction (playbook §5.3/§5.4) with explicit sign-off in this run.
3. **You do not perform destructive or platform-level operations.** Do not rename repos or the org, delete packages/images/CRDs, change branch-protection rules, or reconfigure Keycloak/SPIRE. If a step needs one of these, flag it for the human owner (playbook §13) and continue with what you can safely do.
4. **One repo, one PR.** No cross-repo edits.
5. **Don't hand-edit generated files.** Regenerate them (deepcopy, CRD manifests, clients) and commit the output.
6. **Assume the repo was already renamed on GitHub** before this run, and you're on a fresh branch off it. If it hasn't been renamed yet, stop and say so.
7. **Sign off every commit** with `git commit -s` (DCO — playbook §11).

---

## Stage 1 — Plan (no edits)

Do this, then present the plan and wait:

1. **Preflight** — run the `gh repo view` guardrail check above. Confirm public + not archived, or STOP.
2. **Identify the repo's target name and new module/package paths** from playbook §2 (e.g. `agent-examples` → `examples`, module `github.com/kagenti/mcp-mitm` → `github.com/rossoctl/mcp-mitm`).
3. **Inventory every reference.** Case-insensitive, grouped by category. Report counts and the concrete strings:
   ```
   grep -rIn -i kagenti . | wc -l
   grep -rInE 'quay.io|ghcr.io' .
   ```
   Break the inventory into: **(a) safe** — brand/prose, Go module & imports, Python/npm, images, Helm charts, CI/workflows, cross-repo links, CODEOWNERS team slugs, `KAGENTI_*` env vars; and **(b) DANGER list** — every runtime-contract occurrence from guardrail #2, quoted with file:line.
4. **State the exact substitutions** you'll apply for the safe set (map old → new per playbook §2).
5. **Flag the DANGER-list items** you will *not* change without sign-off, and note which migration section applies (§5.3 or §5.4).
6. **List the verification** you'll run for this repo (build, tests, lint, chart/manifest validation, e2e if it's cluster-touching — playbook §10).
7. **Describe the PR** you'll open (branch name, emoji title, body with `Related to #1972`).

Then present all of the above as a concise plan and ask: **"Approve this plan, or edit it?"** Do not proceed until the human approves.

---

## Stage 2 — Execute (only after approval)

1. Apply the **safe substitutions** from the approved plan.
2. Update **cross-repo references** (sibling URLs, image refs), **CODEOWNERS** (`@kagenti/* → @rossoctl/*`), and **CI** (reusable-workflow refs, `ALLOWED_REPOS`, display names). Do **not** rename workflow/job names that are required status checks without flagging it (playbook §6).
3. For each **DANGER-list** item, pause and get explicit sign-off before changing it. If sign-off isn't given, leave it and record it as retained.
4. **Regenerate** any generated files; do not hand-edit them.
5. **Run the verification gate** (playbook §10) and report results. If something fails, fix it or surface it — don't call the task done on red.

---

## Stage 3 — Verify & PR

1. Work the **per-repo checklist** in playbook §9 and paste it (checked) into the PR body.
2. **Grep sweep:** `grep -rIn -i kagenti .` should return only the deliberately-retained contracts. Anything else is a miss — fix it.
3. Commit signed off, open the PR per playbook §11 (emoji title, `## Summary`, `## Related issue(s): Related to #1972`), and **report**: what changed, what you retained and why, verification results, and any items you flagged for a human owner.

---

## Definition of done (for one repo)

- Repo confirmed public + active; guardrails respected.
- Safe substitutions applied; DANGER-list items either migrated-with-sign-off or explicitly retained and documented.
- Verification gate green (or failures clearly surfaced, not hidden).
- Signed-off PR open, checklist filled, `Related to #1972`, and a written summary of decisions and flags.

When in doubt, prefer stopping and asking over guessing. A retained `kagenti` string you flagged is fine; a silently-broken cluster contract is not.
