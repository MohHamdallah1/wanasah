# WANASAH Flutter V1 — UI / UX Handoff

## Current status

The earlier Figma A/B/C exploration and temporary **Daylight Signal** direction were rejected by the owner on 2026-10-24. They are not production references.

Figma is optional and must not be a V1 dependency. The project continues from repository-controlled functional mapping plus reviewed visual references and Flutter implementation.

## Approved polish brief

The current target is a deliberate blend of:

- **Clean Modern UI** — contemporary, restrained, coherent and visually distinctive;
- **High Usability** — fast field operation, obvious next action, one-handed use where practical, clear Arabic hierarchy, outdoor readability, and strong offline/service-state communication.

The goal is not “more cards” or a generic AI dashboard. Visual polish must follow actual representative work.

## Mandatory functional source

Before changing any screen, read:

- `design/wanasah_v1/FIELD_FUNCTION_SURFACE_MAP.md`
- `FLUTTER_V1_END_TO_END_CLOSURE_PLAN.md`
- `ARCHITECTURE.md` §12
- `.rules`
- `AGENTS.md`

The FIELD function map defines what each Flutter screen/flow must preserve. A design that looks better but hides or removes an accepted V1 action is not acceptable.

## Screen-by-screen workflow

1. Read the exact current screen functions and states from the FIELD function map.
2. Inspect the current Flutter ownership boundaries for that screen.
3. Produce/review a visual direction using any reliable tool or generated reference; no external design service is mandatory.
4. Owner reviews material visual-direction changes before production implementation.
5. Implement the approved slice in Flutter on a clean branch.
6. While touching that slice, perform only the useful single-responsibility cleanup needed for safe growth.
7. Run focused tests plus the required Flutter gates.
8. Review/merge, then fast-forward the owner checkout to `main`.

## Non-negotiables

- Backend business authority remains Backend authority.
- Persisted FIELD capabilities/scopes remain authorization authority.
- Existing Visit/offline durable command identity/replay remains intact.
- Session, Custody, transfers, returns, pricing/money and reconciliation contracts are not redesigned by UI work.
- Connectivity, service failure and pending synchronization are distinct states.
- File count is not a quality metric; split only real responsibilities.
- The whole Backend is **not** a Flutter surface. Only V1 FIELD functions intended for representatives belong in this app.

## Historical Figma reference

A prior exploration file exists at:
https://www.figma.com/design/kzlrGGIflbZSeCWRSGXOdd

It may be used only as historical exploration. It is **not** the approved V1 visual source and must not block work if unavailable.
