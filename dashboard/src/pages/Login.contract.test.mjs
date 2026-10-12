import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./Login.tsx", import.meta.url), "utf8");

test("canonical dashboard contract has no is_admin alias", () => {
  assert.match(source, /is_company_owner:\s*boolean;/);
  assert.match(source, /dashboard_access:\s*boolean;/);
  assert.match(source, /principal_id:\s*number;/);
  assert.match(source, /backoffice_user_id:\s*number;/);
  assert.doesNotMatch(source, /\bis_admin\b/);
});

test("dashboard admission uses dashboard_access", () => {
  assert.match(source, /if \(data\.dashboard_access !== true\)/);
});

test("owner navigation uses is_company_owner", () => {
  assert.match(source, /navigate\(data\.is_company_owner \? '\/' : '\/inventory'\);/);
});

test("driver_id localStorage compatibility remains", () => {
  assert.match(source, /localStorage\.setItem\('driver_id', String\(data\.driver_id\)\);/);
});
