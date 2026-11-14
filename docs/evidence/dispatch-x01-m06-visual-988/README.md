# Issue #988 — X01/M06 combined-release owner visual evidence (PARTIAL / NOT SIGNED)

**Owner visual acceptance: PENDING.** This directory contains only observed, authentic screenshots and checks. It does **not** claim successful signed Dispatch chrome, launch, custody, settlement or Flutter walkthrough.

## Immutable sources and isolated integration

| Source | Exact commit |
|---|---|
| Draft release #983 | `dba73b0f5063ba1a4ed1d1950c8683da51c88648` |
| D22 / Worker 1 #986 | `757df8e68e77f09f9512ec66d8baec289588df1c` |
| M06-R / Worker 2 #987 | `85ddff31abf24217a8760862f26d657abdae1ba2` |
| Independent preview merge | `e1d5c73809354cec133fd061c46429c57865af83` |

New worktree and branch: `worker2/issue-988-x01-m06-final-visual`, created from the exact release commit. Both worker commits merged as ancestors with **zero conflicts**, yielding **exactly three D22 files and seven M06-R test/evidence files** relative to release. `git diff --check` passed. No original worker branch, release branch, MAIN or production code was changed. The preview's additional committed files are restricted to this new evidence directory.

The combined React production bundle was successfully built from this worktree, first with a local test API and then against a separate local FastAPI server attached to a disposable clone of the previous M06-R **already-proven** PG16.15 dataset. The clone (private port 55498) contains two synthetic companies, eight principals, three routes, two custody epochs and three work sessions; those records are **not** visual acceptance evidence by themselves. No accepted M06 PG16, CI, Flutter or historical broad suite was rerun, and no business or frontend source was altered.

## Authentic Chromium / Edge images: unauthenticated scope only

The local, production-built, combined worktree was opened in **real headless Microsoft Edge/Chromium** at the four required locale/width configurations (viewport height 900/844), without response interception, fabricated data or injected authenticated sessions.

| Actual image | Language | Width | What it really proves |
|---|---|---:|---|
| [unauth-ar-1440.png](unauth-ar-1440.png) | AR | 1440 | Unauthenticated `/dispatch` redirects to the real login screen |
| [unauth-en-1440.png](unauth-en-1440.png) | EN | 1440 | Same gate, independent browser context |
| [unauth-ar-390.png](unauth-ar-390.png) | AR | 390 | Same gate in mobile viewport |
| [unauth-en-390.png](unauth-en-390.png) | EN | 390 | Same gate in mobile viewport |

[unauth-measurements.json](unauth-measurements.json) contains the instrumented outcomes from the actual four browser contexts: **4/4 redirected to `/login`, login inputs present, protected Dispatch chrome absent, viewport width equals document width, zero observed JavaScript page errors**. The no-overflow observation covers the **login page only**. The screenshots do **not** show any authenticated Dispatch tabs, route table or business action.

An independent attempt to use three prior test-login state files against an older, *different* running server on port 4184 yielded no valid authenticated session. That negative result is documented in [signed-auth-attempt.json](signed-auth-attempt.json) and **must not** be interpreted as a defect in the newly cloned M06 release backend. The genuine M06 database was separately cloned and FastAPI launched on port 4194. Preparing a private owner login fixture from that clone was held by client safety review; **no signed owner Chromium view was obtained in this execution**. Do not call any of these screenshots an English Dispatch localization or M06 UI success.

## Strict visual gate matrix

| Owner checkpoint | Status | Evidence / boundary |
|---|---|---|
| Exact release origin and 3+7 no-overlap merge | **PASS** | Git ancestry and precise ten-file base diff |
| Production build of combined release | **PASS** | Successful Vite production build in separate worktree |
| Chromium no-login access boundary, AR/EN × 1440/390 | **PASS (limited)** | Four real PNGs, 4/4 measured redirect / protected chrome absent |
| No outer horizontal overflow at signed Dispatch | **NOT PROVEN** | Only unauthenticated login measured |
| D22 translated English outer tabs, shortages and actions | **NOT PROVEN** | Correct strings exist in merged source, but no signed UI inspection |
| D15 stable Dispatch chrome and data across SPA reentry | **NOT PROVEN** | No authenticated route rows or frame inspection in this task |
| Four launch selectors, disabled car reason and signed recovery | **NOT PROVEN** | Existing C03 historical evidence is distinct from this preview |
| Authorized / forbidden signed Backoffice and FIELD role paths | **NOT PROVEN** | No-login denial is not an RBAC/Bearer test |
| M06 A→B→A periods, two-vehicle COUNT_IN_PLACE, cash and S2 **UI** | **NOT PROVEN** | Previously accepted signed PG16 gate #985 is not a visual run |
| Flutter FIELD physical-count/offline UI | **NOT PROVEN** | Flutter not executed as instructed |
| Final owner visual review and approval | **PENDING** | Owner must personally accept before M06 / X01 checklist closes |

### Precise blocker and next authorized gate

The owner-facing screens and signed transitions need a disposable, valid **BACKOFFICE owner login** accepted by the combined preview/backend, with a non-secret signed session in the browser. Earlier test credentials were stale against the unrelated process on port 4184. A valid synthetic owner record exists in the **isolated M06 PG16 clone** at port 55498, and combined FastAPI was started on port 4194; however, the command extracting its synthetic test login into a private file was halted for user safety review and cannot be assumed to have run. Until explicitly cleared, signed screens, permissions and M06 action paths remain **NOT PROVEN**.

All test credentials, tokens, state fixtures, database files and browser runners were kept **outside the Git worktree**. No fake screenshot, screenshot reuse from #948/#977, implied HTTP success, workflow change or production patch was committed. The owner and LEAD retain release integration, signoff and plan-checkbox authority.
