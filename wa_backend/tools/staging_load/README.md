# Wanasah D7-S — independent mixed staging load driver

Permanent optional operational tooling, **not** an application worker, migration,
Product Import feature, or daily testing requirement.

- **Runner:** `wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py`
- **Fail-closed configuration:** `wanasah_d7s_mixed_load_config.py`
- **Independent contract tests:** `wa_backend/tests/test_staging_d7s_mixed_load_contract.py`
- **Complete operator guide and safety boundaries:** `docs/operations/WANASAH_D7S_MIXED_LOAD_TOOL.md`
- **Owner:** V2 multi-company / 1,000 simultaneous real HTTP/TLS connection qualification,
  tracked in `VERSION_2_FUTURE_FEATURES.md` §8 and GitHub Issue #38.

From the `wa_backend` directory, the import-safe *plan-only* entrypoint is
`python -m tools.staging_load.wanasah_d7s_mixed_load_driver`. It requires an explicit
valid environment manifest even in plan-only mode and never falls back to
developer/production credentials. **Do not use live `--execute` flags without the
owner's authorization, isolated synthetic staging, and the operator guide's
independent ingress/SQL/accounting evidence.**

This directory deliberately stays outside the historical `scripts/` test and
migration utilities; moving or deleting unrelated `scripts/` files is not
part of this change. Original work was preserved on the Codex D7S branch.
