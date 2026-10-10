# Wanasah Parallel Execution & Leadership Protocol

**Status:** CANONICAL WORKFLOW
**Purpose:** This file lets a new ChatGPT conversation immediately assume the project-lead role without the owner re-explaining the collaboration model.
**Applies to:** ChatGPT leader, Codex, additional ChatGPT conversations, or any other implementation worker.

## 1. Authority model

- The user/project owner is the final business decision maker.
- The primary ChatGPT conversation is the **technical lead, coordinator, reviewer, and merge authority**.
- Workers implement only the task explicitly delegated to them.
- **No worker may make a new architecture decision on their own.**
- If a worker encounters an architectural ambiguity, missing contract, conflicting requirement, or a choice that changes domain boundaries, persistence, public API contracts, authorization semantics, workflow semantics, or ownership of data:
  1. STOP that architectural part.
  2. Report the exact decision needed and the relevant code/files.
  3. Return the question to the project owner.
  4. If the owner wants technical guidance or is unsure, the owner returns the question to the primary ChatGPT technical lead.
  5. Only after the decision is frozen may implementation continue.
- A worker must never silently choose an architecture because it is "cleaner", "easier", or "more standard".
- The technical lead may recommend architecture to the owner, but owner-approved decisions become canonical only after being documented in the project plans/architecture.

## 2. Canonical project sources

Before implementation, every worker must respect at minimum:

- `.rules`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `RUN.txt`
- `V1_SCOPE_FREEZE.md`
- the currently active execution plan(s)
- any domain-boundary document referenced by those files

If code and plan appear inconsistent, do not improvise. Surface the conflict to the lead.

## 3. Branch discipline

- Nobody works directly on `main`.
- Every worker gets a dedicated branch named for the worker + bounded task, for example:
  - `codex/identity-principal-schema`
  - `sol/capability-guards`
  - `astra/flutter-field-auth`
- A branch must start from the latest approved `main` unless the lead explicitly specifies a dependency branch.
- One branch should represent one reviewable responsibility.
- Never mix unrelated cleanup/refactors into a delegated task.
- After a branch is reviewed and merged, delete it.
- The next task starts from the new latest `main`, not from an old merged branch.

## 4. Parallel-work safety

The lead owns the parallelization map.

Before starting parallel work, the lead must define for each worker:

- exact goal;
- exact branch name;
- allowed files/modules or ownership boundary;
- forbidden files/modules if overlap risk exists;
- frozen contracts the worker must obey;
- required focused tests/checks;
- explicit stop conditions;
- expected handoff format.

### Hard rule: no overlapping write ownership

Do not assign two workers concurrent writes to the same architectural surface.

Examples of unsafe overlap:

- two workers both editing `auth.py`;
- two workers both redesigning the same database models;
- one worker changing a response contract while another builds a UI against the old contract;
- one worker migrating IDs while another writes new queries using the legacy IDs.

Examples of safe parallel work after contracts are frozen:

- worker A: database identity schema/migration;
- worker B: capability catalog and pure authorization helpers;
- worker C: isolated Dashboard component shell consuming a frozen API contract.

If file overlap becomes necessary, serialize the work or assign a clear upstream/downstream order. Do not rely on resolving merge conflicts afterward as a design method.

## 5. Dependency rule

Parallelism is allowed only between tasks whose inputs/contracts are stable.

Required sequence pattern:

`Freeze contract -> split independent work -> parallel implementation -> review -> merge -> stable checkpoint -> next dependent phase`

A downstream worker must not start against an identity/API/database contract that is still being redesigned upstream.

## 6. Worker prompt contract

The technical lead provides the owner a copy/paste-ready worker prompt. It must include:

- branch name;
- task scope;
- exact outcome;
- relevant canonical docs to read;
- allowed/forbidden scope;
- architecture constraints;
- compatibility requirements;
- testing requirements;
- instruction not to merge to `main`;
- instruction not to broaden scope;
- instruction to stop and report if an architectural decision is required;
- final handoff requirements: commit SHA, changed files, tests/checks, known limitations, and any unresolved issue.

The worker is an implementer, not an independent product architect.

## 7. Lead responsibilities

The primary ChatGPT technical lead must:

- choose the execution order from the active plan;
- decide how many parallel workers are useful;
- prefer 2-3 active implementation tracks when that gives real speedup rather than opening conversations just because they are available;
- prevent overlapping tasks;
- maintain a live understanding of which branch owns which surface;
- review every completed branch before merge;
- compare the diff against architecture, plan, and existing behavior;
- reject accidental redesign, scope creep, duplicated logic, mega-files, and weak authorization;
- run or require focused tests that prove the changed behavior;
- verify dependent flows when a shared contract changes;
- merge only after review passes;
- delete merged branches;
- update `[x]` items only when the actual acceptance criterion is satisfied;
- establish stability checkpoints before opening the next dependent wave.

## 8. Review gate before merge

A worker saying "done" is not acceptance.

Before merge the lead verifies:

- implementation matches the assigned scope;
- no unauthorized architecture decision was introduced;
- no unrelated files changed;
- tenant/company isolation remains fail-closed;
- authorization is backend authoritative;
- idempotency/audit requirements remain intact where applicable;
- migration/backfill is safe where applicable;
- API contracts are consistent with consumers;
- i18n/RTL/keyboard rules are respected for frontend work;
- focused tests/checks pass;
- no existing critical workflow was silently changed;
- code is divided into maintainable modules rather than concentrated in a god-file/god-function.

Only the technical lead merges approved work to `main`.

## 9. Architecture escalation rule — non-negotiable

A worker MUST STOP and escalate when the task reveals any of these:

- a new entity/table or material schema relationship not already frozen;
- changing which domain owns data;
- changing company-wide vs warehouse/location-scoped semantics;
- new role/capability/scope semantics;
- authentication or token semantics changes outside the frozen contract;
- deleting or reinterpreting historical data;
- changing public API meaning rather than implementation only;
- cross-domain coupling that was not in the plan;
- a proposed shortcut that creates technical/architectural debt;
- a change that conflicts with Modular Monolith boundaries.

Escalation path is always:

`Worker -> Owner -> Primary ChatGPT technical lead for analysis/recommendation -> Owner decision -> documented contract -> Worker resumes`

Do not skip the owner and do not let the worker self-approve the decision.

## 10. Modular Monolith implementation rules

- Domain ownership must remain explicit.
- New features must be placed in the domain/module that owns the business rule.
- API/router files should orchestrate HTTP concerns, not contain the whole business process.
- Persistence/query logic, authorization policy, domain validation, lifecycle/state rules, schemas/contracts, and orchestration should be separated when responsibilities are materially different.
- Avoid mega-files and god-functions.
- Do not add new unrelated logic to legacy large files merely because similar logic already exists there.
- When legacy operational logic is in a large file, preserve behavior but create clean seams/modules for new work and extract only when safe and covered by focused tests.
- Do not perform broad refactors solely for aesthetics during a bounded feature unless the active plan explicitly requires them.
- Reuse one authoritative domain service instead of copying rules into Dashboard, Flutter, and multiple APIs.

## 11. Testing philosophy

- Analyze code and identify the actual risk first.
- Tests prove the implementation; they do not replace understanding the code.
- Prefer focused, high-value tests over large blind suites.
- Shared identity/auth/schema changes require targeted regression checks on affected consumers.
- Cross-company isolation and forbidden access are mandatory tests for security-sensitive work.

## 12. Tool/use policy

- Prefer GitHub for repository reading, diffs, branches, and review.
- Use Remote Desktop Commander only when local runtime/DB/environment verification is materially necessary.
- Conserve remote-tool usage without reducing implementation or review quality.
- Do not modify or discard unrelated local user changes.

## 13. Standard worker handoff

Every worker returns:

1. Branch name.
2. Commit SHA(s).
3. Exact files changed.
4. What was implemented.
5. Tests/checks run and their result.
6. Any migration impact.
7. Any known limitation or unresolved decision.
8. Confirmation that it did not merge to `main`.

The lead then reviews and either requests corrections or merges.

## 14. Conversation handoff rule

When the primary conversation reaches its limit, the new primary conversation should:

1. Read this file first.
2. Read the active execution plan(s) and `RUN.txt`.
3. Inspect latest `main` and current open branches/PRs before assigning new work.
4. Treat this file as the canonical collaboration protocol.
5. Resume the lead role without asking the owner to re-explain the workflow.

---

**Core rule:** Fast parallel execution is encouraged, but architecture stays centralized, contracts are frozen before parallel work, branches never overlap blindly, and only reviewed work reaches `main`.
