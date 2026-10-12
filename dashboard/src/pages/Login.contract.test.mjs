import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./Login.tsx", import.meta.url), "utf8");

test("canonical dashboard contract has no is_admin alias", () => {
  assert.match(source, /is_company_owner:\s*boolean;/);
  assert.match(source, /dashboard_access:\s*boolean;/);
  assert.match(source, /principal_id:\s*number;/);
  assert.match(source, /backoffice_user_id:\s*number;/);
  assert.match(source, /channel:\s*'DASHBOARD';/);
  assert.match(source, /principal_type:\s*'BACKOFFICE';/);
  assert.doesNotMatch(source, /\bis_admin\b/);
});

test("dashboard admission uses canonical channel and dashboard_access", () => {
  assert.match(source, /if \(data\.dashboard_access !== true\)/);
  assert.match(source, /data\.channel !== 'DASHBOARD'/);
  assert.match(source, /data\.principal_type !== 'BACKOFFICE'/);
});

test("owner navigation uses is_company_owner", () => {
  assert.match(source, /navigate\(data\.is_company_owner \? '\/' : '\/inventory'\);/);
});

test("canonical Dashboard IDs are persisted independently", () => {
  assert.match(source, /localStorage\.setItem\('principal_id', String\(principalId\)\);/);
  assert.match(source, /localStorage\.setItem\('backoffice_user_id', String\(backofficeUserId\)\);/);
  assert.match(source, /localStorage\.removeItem\('driver_id'\);/);
  assert.doesNotMatch(source, /data\.driver_id/);
  assert.doesNotMatch(source, /data\.driver_name/);
});
