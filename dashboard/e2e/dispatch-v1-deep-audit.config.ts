import { defineConfig } from "playwright/test";

const locales = ["ar", "en"] as const;
const sizes = [{name:"1440",width:1440,height:900},{name:"700",width:700,height:900},{name:"390",width:390,height:844}];
export default defineConfig({
  testDir: ".", testMatch: "dispatch-v1-deep-audit.spec.ts",
  workers: 1, retries: 0, timeout: 90_000, expect: { timeout: 12_000 },
  reporter: [["list"],["json",{outputFile:"../node_modules/.cache/dispatch-v1-deep-audit/results.json"}]],
  outputDir:"../node_modules/.cache/dispatch-v1-deep-audit/results",
  projects: locales.flatMap(locale => sizes.map(size => ({
    name:`${locale}-${size.name}`, use:{locale:locale === "ar"?"ar-JO":"en-US",
      viewport:{width:size.width,height:size.height}, browserName:"chromium",headless:true,
      baseURL:"http://127.0.0.1:4173", actionTimeout:12_000,navigationTimeout:30_000,
      trace:"retain-on-failure",screenshot:"only-on-failure"},
    metadata:{locale,width:size.width},
  }))),
});
