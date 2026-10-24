# WANASAH Flutter V1 — Daylight Signal Design Handoff

Figma source of truth:
https://www.figma.com/design/kzlrGGIflbZSeCWRSGXOdd

## Purpose

This folder is the repository-side mirror of the approved WANASAH Flutter V1 visual direction.
The native Figma file remains cloud-native and is not replaced by a checked-in `.fig` snapshot.
Flutter implementation must use this handoff plus the live Figma reference; business contracts remain frozen by the existing project architecture and V1 plans.

## Visual direction

**Daylight Signal** combines:
- high daylight/outdoor readability;
- bold operational signaling;
- Arabic-first composition;
- task-first hierarchy;
- minimal decorative dashboard-card behavior;
- preserved cached/local working state during service/connectivity degradation.

Primary typeface: **Alexandria**.

## Foundation

See `daylight_signal_tokens.json`.

### Core color roles

- Canvas: warm off-white, not pure white.
- Surface: slightly warmer elevated surface.
- Ink: near-black operational surface.
- Amber: primary attention / start-work / pending state.
- Lime: positive actionable highlight.
- Signal blue: active operational state and current-route emphasis.
- Success green: connected/synchronized evidence.
- Danger red: destructive action / service failure evidence.

## Field Home states

The live Figma page **02 — Field Home** currently contains these reference states:

1. **Field Home / Ready**
   - no active Work Session;
   - start-work command;
   - sync/connection evidence;
   - representative, region and date context;
   - route progress;
   - cash custody;
   - vehicle inventory;
   - visits entry;
   - quiet Recovery state.

2. **Field Home / Active**
   - active Work Session;
   - started-at evidence;
   - explicit **Start break** and **End work** actions;
   - route/custody/visits remain visible.

3. **Field Home / Break**
   - active Work Session in break state;
   - explicit **End break** and **End work** actions;
   - route state remains preserved.

4. **Field Home / Connectivity Cached**
   - cached/local screen remains usable;
   - warning says system reachability is temporarily unavailable;
   - must not mislabel every service problem as "no internet".

5. **Field Home / Service Cached**
   - cached/local screen remains usable;
   - service failure is visually distinct from device/network connectivity failure;
   - raw HTTP/internal server details are not shown to the representative.

6. **Field Home / Recovery Pending**
   - pending synchronization evidence is explicit and non-destructive;
   - local data is described as preserved;
   - Recovery detail/sync action remains discoverable.

## Pending design work

- Pending transfer acceptance/rejection dialog in the same visual language.
- Work-session action-issue state.
- Additional blocked Recovery evidence state when durable evidence requires operator attention.
- Visit list.
- Visit detail / operation selection.
- Sale / collection / sample / return flows.
- Shop creation.
- Custody / inventory sections.
- Login and remaining support/error surfaces.

## Review workflow

For each UI slice:

1. Design/reference state is created or updated in Figma.
2. User reviews the design before production implementation when visual direction changes materially.
3. Approved slice is implemented in Flutter on a clean branch.
4. Existing business authority remains unchanged.
5. Focused tests + Flutter gates run.
6. PR is reviewed/merged.
7. Local development checkout fast-forwards to `main`.

Minor spacing/copy consistency fixes that do not change the accepted visual direction may be applied during implementation and then reflected back into this handoff.

## Important

A checked-in Figma export would be a static snapshot, not a live two-way synchronized design source.
Do not treat a `.fig` export as authoritative over the live Figma file and this repository handoff.
